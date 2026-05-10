"""Views.

Every status mutation goes through `shop.workflow`. Every notification is
emitted via `shop.events.emit(...)`; views never call providers directly.
Every state change writes an AuditLog row through `shop.services.audit`.
"""
from __future__ import annotations

from calendar import monthcalendar
from datetime import datetime, time, timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from shop import events, workflow
from shop.forms import (
    CustomerForm, CustomerOrderForm, DamageIncidentForm, DeliveryForm,
    MeasurementForm, OrderItemForm, PaymentForm, TaskAssignmentForm,
    TicketStatusUpdateForm, WorkTicketForm,
)
from shop.models import (
    Appointment, Attachment, AuditLog, Currency, Customer, CustomerOrder,
    DamageIncident, DiscountRule, Employee, ExchangeRate,
    GarmentCategory, Lead, Material, MaterialRequest, Measurement,
    NotificationLog, NotificationPreference, OrderItem,
    OrderTemplate, Payment, ProductionStage, ReferralCode,
    Supplier, SupplierOrder, SupplierOrderLine,
    TaskAssignment, TicketStatusHistory, WorkTicket,
)
from shop.services import audit, billing, booking_dates, documents, intake as intake_service
from shop.services import display_currency as display_currency_service
from shop.services import inventory as inventory_service
from shop.services import pricing as pricing_service
from shop.services import qr as qr_service
from shop.services import ticket_defaults as ticket_defaults_service


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────


def _get_employee(request):
    if not request.user.is_authenticated:
        return None
    try:
        return Employee.objects.get(user=request.user)
    except Employee.DoesNotExist:
        return None


def _authenticate_by_email_or_username(request, email, password):
    user = authenticate(request, username=email, password=password)
    if user is not None:
        return user
    if not email or not password:
        return None
    for u in User.objects.filter(email__iexact=email):
        candidate = authenticate(request, username=u.username, password=password)
        if candidate is not None:
            return candidate
    return None


def _is_staff(user):
    return user.is_authenticated and user.is_staff


def _wants_json(request):
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.headers.get('Accept', '').startswith('application/json')
    )


def emp_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('emp_login')
        emp = _get_employee(request)
        if not emp:
            if request.user.is_staff:
                return redirect('dashboard')
            return redirect('emp_login')
        return view_func(request, *args, employee=emp, **kwargs)
    return wrapper


# ────────────────────────────────────────────────────────────────────────
#  Staff dashboard
# ────────────────────────────────────────────────────────────────────────


@login_required
def dashboard(request):
    today = timezone.now().date()

    total_orders = CustomerOrder.objects.count()
    pending_orders = CustomerOrder.objects.filter(status__in=['draft', 'received']).count()
    in_production = CustomerOrder.objects.filter(status='in_production').count()
    completed_orders = CustomerOrder.objects.filter(status='completed').count()
    delivered_orders = CustomerOrder.objects.filter(status='delivered').count()
    overdue_orders = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).count()
    open_tickets = WorkTicket.objects.filter(status__in=['open', 'assigned', 'in_progress']).count()
    overdue_tickets = WorkTicket.objects.filter(
        deadline__lt=today
    ).exclude(status__in=['completed', 'cancelled']).count()
    blocked_tickets = WorkTicket.objects.filter(status='blocked').count()
    damage_count = DamageIncident.objects.filter(is_resolved=False).count()
    due_soon = CustomerOrder.objects.filter(
        due_date__range=[today, today + timedelta(days=3)]
    ).exclude(status__in=['delivered', 'cancelled']).count()

    low_stock = [m for m in Material.objects.filter(is_active=True) if m.is_low_stock]
    pending_requests = MaterialRequest.objects.filter(status='pending').count()
    new_leads = Lead.objects.filter(status='new').count()
    recent_orders = CustomerOrder.objects.select_related('customer').order_by('-created_at')[:8]
    urgent_tickets = WorkTicket.objects.filter(
        priority__in=['high', 'urgent']
    ).exclude(status__in=['completed', 'cancelled']).select_related(
        'order_item__order__customer', 'current_stage'
    ).order_by('-priority', 'deadline')[:6]

    stages = ProductionStage.objects.annotate(
        ticket_count=Count('active_tickets', filter=Q(
            active_tickets__status__in=['open', 'assigned', 'in_progress']
        ))
    ).order_by('stage_order')
    overdue_ids = list(
        CustomerOrder.objects.filter(
            due_date__lt=today,
        ).exclude(status__in=['delivered', 'cancelled']).values_list('pk', flat=True)
    )
    cal_year, cal_month = today.year, today.month
    cal_weeks = monthcalendar(cal_year, cal_month)
    cal_heading = today.strftime('%B %Y')
    due_day_numbers = list(
        CustomerOrder.objects.filter(
            due_date__year=cal_year,
            due_date__month=cal_month,
        )
        .exclude(status__in=['delivered', 'cancelled'])
        .values_list('due_date__day', flat=True)
        .distinct()
    )
    rail_end = today + timedelta(days=14)
    rail_items = []
    for o in (
        CustomerOrder.objects.filter(due_date__gte=today, due_date__lte=rail_end)
        .exclude(status__in=['delivered', 'cancelled'])
        .select_related('customer').order_by('due_date')[:5]
    ):
        rail_items.append({'date': o.due_date, 'title': f'Order #{o.pk}',
                            'sub': o.customer.full_name, 'url': 'order_detail', 'pk': o.pk})
    for t in (
        WorkTicket.objects.filter(deadline__gte=today, deadline__lte=rail_end)
        .exclude(status__in=['completed', 'cancelled'])
        .select_related('order_item__order__customer')[:5]
    ):
        rail_items.append({'date': t.deadline, 'title': t.ticket_code,
                            'sub': t.order_item.order.customer.full_name,
                            'url': 'ticket_detail', 'pk': t.pk})
    rail_items.sort(key=lambda x: x['date'])
    highlight_order = recent_orders[0] if recent_orders else None

    context = {
        'total_orders': total_orders, 'pending_orders': pending_orders,
        'in_production': in_production, 'completed_orders': completed_orders,
        'delivered_orders': delivered_orders, 'overdue_orders': overdue_orders,
        'overdue_ids': overdue_ids, 'open_tickets': open_tickets,
        'overdue_tickets': overdue_tickets, 'blocked_tickets': blocked_tickets,
        'damage_count': damage_count, 'due_soon': due_soon,
        'low_stock_count': len(low_stock),
        'pending_requests': pending_requests, 'new_leads': new_leads,
        'recent_orders': recent_orders, 'urgent_tickets': urgent_tickets,
        'stages': stages, 'today': today,
        'cal_weeks': cal_weeks, 'cal_heading': cal_heading,
        'cal_month': cal_month, 'cal_year': cal_year,
        'due_day_numbers': due_day_numbers,
        'rail_items': rail_items, 'highlight_order': highlight_order,
    }
    return render(request, 'shop/dashboard.html', context)


# ────────────────────────────────────────────────────────────────────────
#  Customers (staff-side)
# ────────────────────────────────────────────────────────────────────────


@login_required
def customer_list(request):
    q = request.GET.get('q', '')
    customers = Customer.objects.annotate(order_count=Count('orders'))
    if q:
        customers = customers.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(phone__icontains=q) | Q(email__icontains=q)
        )
    return render(request, 'shop/customer_list.html', {'customers': customers, 'q': q})


@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            audit.log(actor=request.user, action='customer.created', target=customer,
                      before={}, after={'name': customer.full_name})
            messages.success(request, f'Customer {customer.full_name} registered successfully.')
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm()
    return render(request, 'shop/customer_form.html', {'form': form, 'title': 'Register New Customer'})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    orders = customer.orders.select_related().prefetch_related('items').order_by('-created_at')
    return render(request, 'shop/customer_detail.html', {'customer': customer, 'orders': orders})


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            before = {'phone': customer.phone, 'email': customer.email, 'address': customer.address}
            form.save()
            audit.log(actor=request.user, action='customer.updated', target=customer,
                      before=before, after={'phone': customer.phone, 'email': customer.email})
            messages.success(request, 'Customer updated successfully.')
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'shop/customer_form.html', {
        'form': form, 'customer': customer, 'title': f'Edit {customer.full_name}'
    })


# ────────────────────────────────────────────────────────────────────────
#  Orders (staff-side)
# ────────────────────────────────────────────────────────────────────────


@login_required
def order_list(request):
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    q = request.GET.get('q', '')
    orders = CustomerOrder.objects.select_related('customer').prefetch_related('items')
    if status_filter:
        orders = orders.filter(status=status_filter)
    if priority_filter:
        orders = orders.filter(priority=priority_filter)
    if q:
        orders = orders.filter(
            Q(customer__first_name__icontains=q) | Q(customer__last_name__icontains=q)
        )
    overdue_ids = [o.pk for o in orders if o.is_overdue]
    return render(request, 'shop/order_list.html', {
        'orders': orders.order_by('-created_at'),
        'status_filter': status_filter, 'priority_filter': priority_filter, 'q': q,
        'overdue_ids': overdue_ids,
        'status_choices': CustomerOrder.STATUS_CHOICES,
        'priority_choices': CustomerOrder.PRIORITY_CHOICES,
    })


@login_required
def order_create(request):
    customer_id = request.GET.get('customer')
    initial = {}
    if customer_id:
        initial['customer'] = customer_id
    if request.method == 'POST':
        form = CustomerOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            order.status = 'received'
            order.save()
            # Freeze an empty snapshot now; will refresh as items get added.
            quote = pricing_service.quote_order(customer=order.customer, items=[])
            pricing_service.freeze_onto_order(order, quote)
            audit.log(actor=request.user, action='order.created', target=order,
                      before={}, after={'status': 'received'})
            events.emit(events.ORDER_CREATED, target=order, actor=request.user, payload={})
            messages.success(request, f'Order #{order.pk} created. Add garment items next.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(initial=initial)
    return render(request, 'shop/order_form.html', {'form': form, 'title': 'Create New Order'})


def _refresh_order_quote(order: CustomerOrder, *, code: str | None = None):
    """Re-quote an order from its current items + applied code, freezing the snapshot."""
    items_payload = [{
        'garment_type': item.garment_type, 'fabric': item.fabric,
        'priority': order.priority, 'quantity': item.quantity,
    } for item in order.items.all()]
    quote = pricing_service.quote_order(
        customer=order.customer,
        items=items_payload,
        code=code if code is not None else (order.applied_discount_code or ''),
        currency_code=order.currency.code if order.currency else 'EUR',
    )
    pricing_service.freeze_onto_order(order, quote,
                                       currency_code=order.currency.code if order.currency else 'EUR')
    # Persist computed unit prices on items (so line totals match the snapshot).
    snap_lines = quote['lines']
    for item, snap in zip(order.items.all(), snap_lines):
        item.unit_price = Decimal(snap['unit_price'])
        item.save(update_fields=['unit_price'])
    return quote


@login_required
def order_detail(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    items = order.items.prefetch_related('measurements', 'tickets', 'damage_incidents', 'attachments')
    payments = order.payments.all()
    delivery = getattr(order, 'delivery', None)
    total_paid = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    remaining_balance = order.final_amount - total_paid
    credit_amount = abs(remaining_balance) if remaining_balance < 0 else Decimal('0.00')
    audit_rows = AuditLog.objects.filter(
        Q(target_type='customerorder', target_id=order.pk)
        | Q(target_type='workticket', target_id__in=WorkTicket.objects.filter(
            order_item__order=order).values_list('pk', flat=True))
        | Q(target_type='payment', target_id__in=order.payments.values_list('pk', flat=True))
    ).order_by('-at')[:30]
    appointments = order.appointments.order_by('scheduled_at')
    return render(request, 'shop/order_detail.html', {
        'order': order, 'items': items, 'payments': payments,
        'delivery': delivery, 'total_paid': total_paid,
        'balance': remaining_balance, 'credit_amount': credit_amount,
        'today': timezone.now().date(),
        'next_states': workflow.next_states(order),
        'audit_rows': audit_rows,
        'appointments': appointments,
        'attachments': order.attachments.all(),
    })


@login_required
def order_edit(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    if request.method == 'POST':
        form = CustomerOrderForm(request.POST, instance=order)
        if form.is_valid():
            before = {'priority': order.priority, 'due_date': str(order.due_date)}
            order = form.save()
            _refresh_order_quote(order)
            audit.log(actor=request.user, action='order.updated', target=order,
                      before=before, after={'priority': order.priority, 'due_date': str(order.due_date)})
            messages.success(request, f'Order #{order.pk} updated.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(instance=order)
    return render(request, 'shop/order_form.html', {
        'form': form, 'order': order, 'title': f'Edit Order #{order.pk}'
    })


@login_required
@require_POST
def order_status_update(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    new_status = request.POST.get('status')
    try:
        workflow.transition(order, to=new_status, actor=request.user,
                             comment=request.POST.get('comment', ''))
        messages.success(request, f'Order status updated to {order.get_status_display()}.')
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect('order_detail', pk=order.pk)


@login_required
def orderitem_create(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method == 'POST':
        form = OrderItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.order = order
            item.save()
            quote = _refresh_order_quote(order)
            messages.success(request, f'Garment "{item.garment_type}" added to order.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = OrderItemForm()
    return render(request, 'shop/orderitem_form.html', {
        'form': form, 'order': order, 'title': 'Add Garment to Order'
    })


@login_required
def orderitem_edit(request, pk):
    item = get_object_or_404(OrderItem, pk=pk)
    if request.method == 'POST':
        form = OrderItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            _refresh_order_quote(item.order)
            messages.success(request, 'Garment updated.')
            return redirect('order_detail', pk=item.order.pk)
    else:
        form = OrderItemForm(instance=item)
    return render(request, 'shop/orderitem_form.html', {
        'form': form, 'order': item.order, 'item': item, 'title': f'Edit {item.garment_type}'
    })


@login_required
def measurement_add(request, item_pk):
    item = get_object_or_404(OrderItem, pk=item_pk)
    if request.method == 'POST':
        form = MeasurementForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.order_item = item
            m.save()
            messages.success(request, 'Measurement recorded.')
            return redirect('order_detail', pk=item.order.pk)
    else:
        form = MeasurementForm()
    return render(request, 'shop/measurement_form.html', {'form': form, 'item': item})


# ────────────────────────────────────────────────────────────────────────
#  Tickets (staff)
# ────────────────────────────────────────────────────────────────────────


@login_required
def ticket_list(request):
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    stage_filter = request.GET.get('stage', '')
    q = request.GET.get('q', '')
    today = timezone.now().date()
    tickets = WorkTicket.objects.select_related(
        'order_item__order__customer', 'current_stage'
    ).prefetch_related('assignments__employee')
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    if priority_filter:
        tickets = tickets.filter(priority=priority_filter)
    if stage_filter:
        tickets = tickets.filter(current_stage__id=stage_filter)
    if q:
        tickets = tickets.filter(
            Q(ticket_code__icontains=q) | Q(order_item__garment_type__icontains=q)
            | Q(order_item__order__customer__first_name__icontains=q)
            | Q(order_item__order__customer__last_name__icontains=q)
        )
    return render(request, 'shop/ticket_list.html', {
        'tickets': tickets.order_by('-created_at'),
        'status_filter': status_filter, 'priority_filter': priority_filter,
        'stage_filter': stage_filter, 'q': q,
        'stages': ProductionStage.objects.all(),
        'status_choices': WorkTicket.TICKET_STATUS_CHOICES,
        'priority_choices': WorkTicket.PRIORITY_CHOICES,
        'today': today,
    })


@login_required
def ticket_create(request, item_pk=None):
    initial = {}
    order_item = None
    if item_pk:
        order_item = get_object_or_404(
            OrderItem.objects.select_related('order', 'order__currency').prefetch_related('measurements'),
            pk=item_pk,
        )
        initial['order_item'] = order_item
        initial.update(ticket_defaults_service.initial_fields_from_order_item(order_item))
    first_stage = ProductionStage.objects.order_by('stage_order').first()
    if first_stage:
        initial['current_stage'] = first_stage
    if request.method == 'POST':
        post_data = request.POST.copy()
        if item_pk and order_item:
            ticket_defaults_service.augment_post_with_defaults(post_data, order_item)
        form = WorkTicketForm(post_data)
        if form.is_valid():
            ticket = form.save(commit=False)
            if ticket.order_item_id:
                defs = ticket_defaults_service.initial_fields_from_order_item(ticket.order_item)
                ticket_defaults_service.merge_saved_ticket_if_blank(ticket, defs)
            ticket.save()
            TicketStatusHistory.objects.create(
                ticket=ticket, stage=ticket.current_stage,
                comment='Ticket created.',
            )
            audit.log(actor=request.user, action='ticket.created', target=ticket,
                      before={}, after={'order_item_id': ticket.order_item_id})
            try:
                workflow.transition(ticket.order_item, to='in_progress', actor=request.user,
                                     comment='Ticket created.')
            except workflow.WorkflowError:
                pass
            order = ticket.order_item.order
            if order.status == 'received':
                try:
                    workflow.transition(order, to='in_production', actor=request.user,
                                         comment='First ticket created.')
                except workflow.WorkflowError:
                    pass
            messages.success(request, f'Work ticket {ticket.ticket_code} created.')
            return redirect('ticket_detail', pk=ticket.pk)
    else:
        form = WorkTicketForm(initial=initial)
    return render(request, 'shop/ticket_form.html', {
        'form': form, 'order_item': order_item, 'title': 'Create Work Ticket'
    })


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    history = ticket.status_history.select_related('stage', 'changed_by').order_by('-changed_at')
    assignments = ticket.assignments.select_related('employee').order_by('-assigned_at')
    incidents = ticket.damage_incidents.select_related('reported_by')
    update_form = TicketStatusUpdateForm()
    assign_form = TaskAssignmentForm()
    qr_data_url = qr_service.qr_png_data_url(ticket.qr_payload)
    return render(request, 'shop/ticket_detail.html', {
        'ticket': ticket, 'history': history, 'assignments': assignments,
        'incidents': incidents,
        'update_form': update_form, 'assign_form': assign_form,
        'today': timezone.now().date(),
        'next_states': workflow.next_states(ticket),
        'attachments': ticket.attachments.all(),
        'qr_data_url': qr_data_url,
    })


@login_required
@require_POST
def ticket_update_stage(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    form = TicketStatusUpdateForm(request.POST)
    if form.is_valid():
        stage = form.cleaned_data['stage']
        try:
            workflow.advance_stage(ticket, to_stage=stage, actor=request.user,
                                    comment=form.cleaned_data.get('comment', ''),
                                    force_skip=request.POST.get('force_skip') == '1')
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=ticket.pk)
        new_status = form.cleaned_data.get('status')
        if new_status and new_status != ticket.status:
            try:
                workflow.transition(ticket, to=new_status, actor=request.user,
                                     comment=form.cleaned_data.get('comment', ''))
            except workflow.WorkflowError as exc:
                messages.warning(request, str(exc))
        messages.success(request, f'Ticket moved to stage: {stage.stage_name}')
    return redirect('ticket_detail', pk=ticket.pk)


@login_required
@require_POST
def ticket_status_update(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    target = request.POST.get('to')
    try:
        workflow.transition(ticket, to=target, actor=request.user,
                             comment=request.POST.get('comment', ''))
        messages.success(request, f'Ticket {ticket.ticket_code} updated.')
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect('ticket_detail', pk=ticket.pk)


@login_required
@require_POST
def ticket_assign(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    form = TaskAssignmentForm(request.POST)
    if form.is_valid():
        ticket.assignments.filter(assignment_status='current').update(
            assignment_status='reassigned', unassigned_at=timezone.now()
        )
        assignment = form.save(commit=False)
        assignment.ticket = ticket
        assignment.assignment_status = 'current'
        assignment.save()
        try:
            workflow.transition(ticket, to='assigned', actor=request.user,
                                 comment=f'Assigned to {assignment.employee.full_name}.')
        except workflow.WorkflowError:
            pass
        audit.log(actor=request.user, action='ticket.assigned', target=ticket,
                  before={}, after={'employee_id': assignment.employee_id})
        events.emit(events.TICKET_ASSIGNED, target=ticket, actor=request.user, payload={
            'employee_id': assignment.employee_id,
        })
        messages.success(request, f'Ticket assigned to {assignment.employee.full_name}.')
    return redirect('ticket_detail', pk=pk)


@login_required
@require_POST
def damage_incident_create(request, ticket_pk):
    ticket = get_object_or_404(WorkTicket, pk=ticket_pk)
    form = DamageIncidentForm(request.POST)
    if form.is_valid():
        incident = form.save(commit=False)
        incident.ticket = ticket
        incident.order_item = ticket.order_item
        incident.save()
        audit.log(actor=request.user, action='incident.reported', target=incident,
                  before={}, after={'severity': incident.severity})
        try:
            workflow.transition(ticket, to='blocked', actor=request.user,
                                 comment=f'Damage: {incident.get_incident_type_display()}')
        except workflow.WorkflowError:
            pass
        events.emit(events.INCIDENT_REPORTED, target=incident, actor=request.user, payload={})
        messages.warning(request, 'Damage incident recorded. Ticket blocked pending resolution.')
    return redirect('ticket_detail', pk=ticket_pk)


@login_required
@require_POST
def damage_incident_resolve(request, pk):
    incident = get_object_or_404(DamageIncident, pk=pk)
    incident.is_resolved = True
    incident.resolution_action = request.POST.get('resolution_action', incident.resolution_action)
    incident.resolution_notes = request.POST.get('resolution_notes', '')
    incident.save()
    audit.log(actor=request.user, action='incident.resolved', target=incident,
              before={'is_resolved': False}, after={'is_resolved': True})
    ticket = incident.ticket
    if not ticket.damage_incidents.filter(is_resolved=False).exists():
        try:
            workflow.transition(ticket, to='in_progress', actor=request.user,
                                 comment='All damage incidents resolved.')
        except workflow.WorkflowError:
            pass
    events.emit(events.INCIDENT_RESOLVED, target=incident, actor=request.user, payload={})
    messages.success(request, 'Incident resolved.')
    return redirect('ticket_detail', pk=incident.ticket.pk)


# ────────────────────────────────────────────────────────────────────────
#  Payments (staff)
# ────────────────────────────────────────────────────────────────────────


@login_required
@require_POST
def payment_add(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        billing.record_payment(
            order=order,
            amount=form.cleaned_data['amount'],
            method=form.cleaned_data.get('payment_method', 'cash'),
            stage=form.cleaned_data.get('payment_stage', 'partial'),
            reference=form.cleaned_data.get('reference_code', ''),
            actor=request.user, channel='staff',
        )
        messages.success(request, f'Payment of {form.cleaned_data["amount"]} recorded.')
    else:
        messages.error(request, 'Invalid payment data.')
    return redirect('order_detail', pk=order_pk)


# ────────────────────────────────────────────────────────────────────────
#  Delivery (staff) — gated by workflow
# ────────────────────────────────────────────────────────────────────────


@login_required
@require_POST
def delivery_create(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    form = DeliveryForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid delivery data.')
        return redirect('order_detail', pk=order_pk)
    try:
        delivery = workflow.schedule_delivery(
            order,
            delivery_date=form.cleaned_data['delivery_date'],
            delivery_method=form.cleaned_data['delivery_method'],
            received_by=form.cleaned_data.get('received_by', ''),
            comments=form.cleaned_data.get('comments', ''),
            actor=request.user,
        )
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
        return redirect('order_detail', pk=order_pk)
    if form.cleaned_data.get('is_delivered'):
        try:
            workflow.confirm_delivery(order, actor=request.user,
                                       received_by=form.cleaned_data.get('received_by', ''))
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
            return redirect('order_detail', pk=order_pk)
    messages.success(request, 'Delivery record created.')
    return redirect('order_detail', pk=order_pk)


@login_required
@require_POST
def delivery_confirm(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    try:
        workflow.confirm_delivery(order, actor=request.user)
        messages.success(request, f'Order #{order.pk} marked as delivered.')
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect('order_detail', pk=order_pk)


# ────────────────────────────────────────────────────────────────────────
#  Reports
# ────────────────────────────────────────────────────────────────────────


@login_required
def report_view(request):
    today = timezone.now().date()
    order_stats = CustomerOrder.objects.values('status').annotate(count=Count('id'))
    overdue_orders = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).select_related('customer').order_by('due_date')
    top_customers = Customer.objects.annotate(
        order_count=Count('orders')
    ).order_by('-order_count')[:10]
    # Reads the FROZEN base_final values (snapshot-only)
    revenue = CustomerOrder.objects.exclude(status='cancelled').aggregate(
        total_invoiced=Sum('base_final'),
        total_paid=Sum('payments__amount'),
    )
    tickets_by_stage = ProductionStage.objects.annotate(
        ticket_count=Count('active_tickets', filter=Q(
            active_tickets__status__in=['open', 'assigned', 'in_progress']
        ))
    ).order_by('stage_order')
    status_counts = {s['status']: s['count'] for s in order_stats}
    order_status_rows = [
        {'key': key, 'label': label, 'count': status_counts.get(key, 0)}
        for key, label in CustomerOrder.STATUS_CHOICES
    ]
    stage_bar_max = max((s.ticket_count for s in tickets_by_stage), default=1)
    unresolved_incidents = DamageIncident.objects.filter(
        is_resolved=False
    ).select_related('order_item__order__customer', 'reported_by')
    # Insights
    most_common = (
        OrderItem.objects.values('garment_type').annotate(c=Count('id')).order_by('-c')[:5]
    )
    deliveries_qs = CustomerOrder.objects.filter(status='delivered').exclude(due_date__isnull=True)
    avg_turnaround_days = None
    if deliveries_qs.exists():
        deltas = [(o.updated_at.date() - o.order_date).days for o in deliveries_qs[:200]]
        deltas = [d for d in deltas if d >= 0]
        if deltas:
            avg_turnaround_days = sum(deltas) / len(deltas)
    repeat_customer_rate = 0
    customer_count = Customer.objects.count()
    if customer_count:
        repeats = Customer.objects.annotate(c=Count('orders')).filter(c__gt=1).count()
        repeat_customer_rate = round(100 * repeats / customer_count, 1)
    unpaid_balance = CustomerOrder.objects.filter(
        payment_status__in=['unpaid', 'partially_paid']
    ).exclude(status='cancelled').aggregate(s=Sum('base_final'))['s'] or Decimal('0.00')
    return render(request, 'shop/report.html', {
        'order_status_rows': order_status_rows, 'stage_bar_max': stage_bar_max,
        'overdue_orders': overdue_orders, 'top_customers': top_customers,
        'revenue': revenue, 'tickets_by_stage': tickets_by_stage,
        'unresolved_incidents': unresolved_incidents,
        'today': today,
        'most_common': most_common,
        'avg_turnaround_days': avg_turnaround_days,
        'repeat_customer_rate': repeat_customer_rate,
        'unpaid_balance': unpaid_balance,
    })


# ────────────────────────────────────────────────────────────────────────
#  Employees (read-only listing)
# ────────────────────────────────────────────────────────────────────────


@login_required
def employee_list(request):
    employees = Employee.objects.filter(is_active=True).annotate(
        active_tasks=Count('task_assignments', filter=Q(task_assignments__assignment_status='current'))
    )
    return render(request, 'shop/employee_list.html', {'employees': employees})


# ────────────────────────────────────────────────────────────────────────
#  Customer portal
# ────────────────────────────────────────────────────────────────────────


def portal_home(request):
    return render(request, 'portal/home.html')


def portal_register(request):
    if (
        request.user.is_authenticated and not request.user.is_staff
        and Customer.objects.filter(user=request.user).exists()
    ):
        return redirect('portal_dashboard')
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        errors = []
        if not first_name or not last_name:
            errors.append('First and last name are required.')
        if not email:
            errors.append('Email is required.')
        elif User.objects.filter(email=email).exists():
            errors.append('An account with this email already exists.')
        if password1 != password2:
            errors.append('Passwords do not match.')
        if len(password1) < 8:
            errors.append('Password must be at least 8 characters.')
        if errors:
            return render(request, 'portal/register.html', {'errors': errors, 'data': request.POST})
        user = User.objects.create_user(
            username=email, email=email,
            password=password1, first_name=first_name, last_name=last_name,
        )
        customer = Customer.objects.create(
            user=user, first_name=first_name, last_name=last_name,
            email=email, phone=phone, address=address,
        )
        ReferralCode.objects.get_or_create(
            customer=customer, defaults={'code': customer.referral_code, 'percent': Decimal('10.00')}
        )
        login(request, user)
        messages.success(request, f'Welcome, {first_name}! Your account has been created.')
        return redirect('portal_dashboard')
    return render(request, 'portal/register.html')


def portal_login(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        if Customer.objects.filter(user=request.user).exists():
            return redirect('portal_dashboard')
        return render(request, 'portal/login.html', {
            'error': 'This account is not linked to a customer profile.',
            'email': request.user.email or request.user.username,
        })
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=email, password=password)
        if user:
            login(request, user)
            if user.is_staff:
                return redirect('dashboard')
            if Customer.objects.filter(user=user).exists():
                return redirect('portal_dashboard')
            return render(request, 'portal/login.html', {
                'error': 'This account is not linked to a customer profile.',
                'email': email,
            })
        return render(request, 'portal/login.html', {'error': 'Invalid email or password.', 'email': email})
    return render(request, 'portal/login.html')


def portal_logout(request):
    logout(request)
    return redirect('portal_home')


def portal_dashboard(request):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('dashboard')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    orders = CustomerOrder.objects.filter(customer=customer).order_by('-order_date')
    active = orders.exclude(status__in=['delivered', 'cancelled'])
    completed = orders.filter(status__in=['delivered', 'cancelled'])
    upcoming = active.filter(due_date__isnull=False).order_by('due_date')[:8]
    appointments = customer.appointments.exclude(status__in=['cancelled', 'no_show']).order_by('scheduled_at')[:5]
    templates = customer.order_templates.order_by('-created_at')[:5]
    return render(request, 'portal/dashboard.html', {
        'customer': customer, 'active_orders': active, 'completed_orders': completed,
        'upcoming_orders': upcoming, 'appointments': appointments,
        'templates': templates,
    })


def portal_order_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('order_detail', pk=pk)
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    order = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    items = order.items.prefetch_related(
        'tickets__current_stage', 'tickets__status_history__stage', 'attachments',
    ).all()
    delivery = getattr(order, 'delivery', None)
    payments = order.payments.all()
    paid = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    balance = (order.final_amount or Decimal('0.00')) - paid
    return render(request, 'portal/order_detail.html', {
        'order': order, 'items': items, 'delivery': delivery,
        'payments': payments, 'balance': balance,
        'snapshot': order.pricing_snapshot or {},
    })


def portal_book(request):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('dashboard')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')

    GARMENT_TYPES = list(GarmentCategory.objects.filter(is_active=True).values_list('name', flat=True))
    if not GARMENT_TYPES:
        GARMENT_TYPES = ['Dress', 'Blouse', 'Skirt', 'Trousers', 'Suit Jacket',
                         'Wedding Gown', 'Shirt', 'Coat', 'Alteration', 'Other']

    if request.method == 'POST':
        due_date = request.POST.get('due_date')
        notes = request.POST.get('notes', '').strip()
        priority = request.POST.get('priority', 'normal')
        garment_type = request.POST.get('garment_type', '').strip()
        fabric = request.POST.get('fabric', '').strip()
        color = request.POST.get('color', '').strip()
        special_instructions = request.POST.get('special_instructions', '').strip()
        quantity = int(request.POST.get('quantity', 1) or 1)
        applied_code = request.POST.get('applied_code', '').strip()
        if not due_date or not garment_type:
            return render(request, 'portal/book.html', {
                'error': 'Please fill in all required fields.',
                'data': request.POST, 'garment_types': GARMENT_TYPES,
            })
        try:
            due_parsed = datetime.strptime(due_date, '%Y-%m-%d').date()
        except ValueError:
            return render(request, 'portal/book.html', {
                'error': _('Please enter a valid due date.'),
                'data': request.POST, 'garment_types': GARMENT_TYPES,
            })
        if not booking_dates.is_due_date_allowed_booking(due_parsed):
            return render(request, 'portal/book.html', {
                'error': _('Your due date must be later than today.'),
                'data': request.POST, 'garment_types': GARMENT_TYPES,
            })
        order = CustomerOrder.objects.create(
            customer=customer, due_date=due_parsed, priority=priority,
            status='received', payment_status='unpaid',
            customer_notes=special_instructions or notes,
        )
        item = OrderItem.objects.create(
            order=order, garment_type=garment_type, fabric=fabric, color=color,
            quantity=quantity, special_instructions=special_instructions,
        )
        book_currency = 'EUR'
        if customer.preferred_currency_id:
            book_currency = customer.preferred_currency.code
        quote = pricing_service.quote_order(
            customer=customer,
            items=[{
                'garment_type': garment_type, 'fabric': fabric,
                'priority': priority, 'quantity': quantity,
            }],
            code=applied_code,
            currency_code=book_currency,
        )
        if applied_code and quote['discount'] <= 0:
            messages.warning(
                request,
                _('The discount or referral code could not be applied to this order.'),
            )
        pricing_service.freeze_onto_order(order, quote, currency_code=book_currency)
        item.unit_price = Decimal(quote['lines'][0]['unit_price'])
        item.save(update_fields=['unit_price'])
        # Reference image upload
        if 'reference_image' in request.FILES:
            Attachment.objects.create(
                content_type=ContentType.objects.get_for_model(OrderItem),
                object_id=item.pk,
                file=request.FILES['reference_image'],
                kind='reference',
                caption='Customer reference image',
                uploaded_by=request.user,
            )
        # Track referral usage
        snap = quote['snapshot'].get('discount_rule') or {}
        if snap.get('rule') == 'referral_code' and snap.get('referrer_id'):
            referrer = Customer.objects.filter(pk=snap['referrer_id']).first()
            ref = ReferralCode.objects.filter(code__iexact=applied_code).first()
            if referrer and ref:
                ReferralCode.objects.filter(pk=ref.pk).update(uses=F('uses') + 1)
                from shop.models import CustomerReferral
                CustomerReferral.objects.create(
                    referrer=referrer, referee=customer, order=order,
                    code_used=applied_code,
                    reward_amount=Decimal(snap.get('applied_amount', '0.00')),
                )
        audit.log(actor=request.user, action='order.created', target=order,
                  before={}, after={'status': 'received'},
                  message='Customer self-booking via portal.')
        events.emit(events.ORDER_CREATED, target=order, actor=request.user, payload={
            'self_service': True, 'item_count': 1,
        })
        messages.success(
            request, f'Your booking #{order.pk} has been submitted and priced automatically.',
        )
        return redirect('portal_order_detail', pk=order.pk)

    return render(request, 'portal/book.html', {'garment_types': GARMENT_TYPES})


def portal_profile(request):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    if request.method == 'POST':
        before = {'phone': customer.phone, 'language': customer.language}
        customer.phone = request.POST.get('phone', '').strip()
        customer.address = request.POST.get('address', '').strip()
        customer.notes = request.POST.get('notes', '').strip()
        customer.language = request.POST.get('language', customer.language) or 'es'
        pref_currency_code = request.POST.get('preferred_currency', '')
        if pref_currency_code:
            customer.preferred_currency = Currency.objects.filter(code=pref_currency_code).first()
        customer.save()
        # Notification preferences
        wanted_channels = set(request.POST.getlist('channels'))
        for channel in ['inapp', 'email', 'sms', 'whatsapp']:
            if request.user:
                NotificationPreference.objects.update_or_create(
                    user=request.user, channel=channel,
                    defaults={'enabled': channel in wanted_channels},
                )
        audit.log(actor=request.user, action='customer.profile_updated', target=customer,
                  before=before, after={'phone': customer.phone, 'language': customer.language})
        messages.success(request, 'Profile updated successfully.')
        return redirect('portal_profile')
    return render(request, 'portal/profile.html', {
        'customer': customer,
        'currencies': Currency.objects.all(),
        'channel_choices': [
            ('inapp', 'In-app'), ('email', 'Email'),
            ('sms', 'SMS'), ('whatsapp', 'WhatsApp'),
        ],
        'enabled_channels': set(
            NotificationPreference.objects.filter(user=request.user, enabled=True)
            .values_list('channel', flat=True)
        ),
    })


# ────────────────────────────────────────────────────────────────────────
#  Customer portal: payment, reorder, appointments
# ────────────────────────────────────────────────────────────────────────


def portal_pay_order(request, pk):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    order = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    paid = order.payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    balance = (order.final_amount or Decimal('0.00')) - paid
    if request.method == 'POST':
        amount_str = request.POST.get('amount', '').strip()
        method = request.POST.get('method', 'card')
        try:
            amount = Decimal(amount_str)
        except Exception:
            messages.error(request, 'Invalid amount.')
            return redirect('portal_pay_order', pk=pk)
        if amount <= 0 or amount > balance:
            messages.error(request, f'Amount must be between 0 and {balance}.')
            return redirect('portal_pay_order', pk=pk)
        billing.record_payment(
            order=order, amount=amount, method=method,
            stage='final' if amount == balance else 'partial',
            reference=f'PORTAL-{request.user.username}',
            actor=request.user, channel='portal',
        )
        messages.success(request, f'Payment of {amount} received. Thank you.')
        return redirect('portal_order_detail', pk=pk)
    checkout = billing.start_checkout(
        order=order,
        success_url=request.build_absolute_uri(reverse('portal_order_detail', kwargs={'pk': pk})),
        cancel_url=request.build_absolute_uri(reverse('portal_order_detail', kwargs={'pk': pk})),
    )
    if checkout.get('mode') == 'redirect' and checkout.get('url'):
        return redirect(checkout['url'])
    display_code = display_currency_service.resolve_display_currency_code(request)
    display_balance = display_currency_service.convert_booking_amount_for_display(
        order, balance, display_code,
    )
    booking_code = display_currency_service.booking_currency_code(order)
    dual = display_code != booking_code
    hint_display = ''
    if dual:
        hint_display = display_currency_service.format_money_amount(display_balance, display_code)
    return render(request, 'portal/pay.html', {
        'order': order,
        'balance': balance,
        'paid': paid,
        'payment_currency_label': booking_code,
        'show_dual_currency_line': dual,
        'display_balance_hint': hint_display,
    })


@csrf_exempt
def payments_webhook(request):
    from shop.providers import payment as payment_provider
    provider = payment_provider.get_provider()
    result = provider.handle_webhook(request=request)
    if result.get('handled') and result.get('order_id'):
        try:
            order = CustomerOrder.objects.get(pk=result['order_id'])
            billing.record_payment(
                order=order, amount=Decimal(str(result.get('amount', 0))),
                method='card', stage='final',
                reference='stripe', actor=None, channel='stripe',
            )
        except CustomerOrder.DoesNotExist:
            pass
    return JsonResponse({'ok': True, **result})


def portal_reorder(request, pk):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    source = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    new_order = CustomerOrder.objects.create(
        customer=customer, status='received', priority=source.priority,
        payment_status='unpaid', notes=source.notes,
    )
    items_payload = []
    for item in source.items.all():
        clone = OrderItem.objects.create(
            order=new_order, garment_type=item.garment_type,
            description=item.description, fabric=item.fabric,
            color=item.color, size_label=item.size_label,
            quantity=item.quantity, special_instructions=item.special_instructions,
        )
        for m in item.measurements.all():
            Measurement.objects.create(
                order_item=clone, measurement_type=m.measurement_type,
                measurement_value=m.measurement_value, unit=m.unit, notes=m.notes,
            )
        items_payload.append({
            'garment_type': item.garment_type, 'fabric': item.fabric,
            'priority': source.priority, 'quantity': item.quantity,
        })
    quote = pricing_service.quote_order(
        customer=customer,
        items=items_payload,
        code=source.applied_discount_code or '',
    )
    pricing_service.freeze_onto_order(new_order, quote)
    audit.log(actor=request.user, action='order.cloned', target=new_order,
              before={}, after={'source_order_id': source.pk})
    messages.success(request, f'Order #{new_order.pk} created from #{source.pk}.')
    return redirect('portal_order_detail', pk=new_order.pk)


def portal_save_template(request, pk):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    source = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    snapshot = {'items': []}
    for item in source.items.all():
        snapshot['items'].append({
            'garment_type': item.garment_type, 'fabric': item.fabric,
            'color': item.color, 'size_label': item.size_label,
            'quantity': item.quantity,
            'special_instructions': item.special_instructions,
            'measurements': [
                {'type': m.measurement_type, 'value': str(m.measurement_value), 'unit': m.unit}
                for m in item.measurements.all()
            ],
        })
    name = request.POST.get('name') or f'Template from #{source.pk}'
    OrderTemplate.objects.create(customer=customer, name=name, snapshot=snapshot)
    messages.success(request, f'Saved template "{name}".')
    return redirect('portal_dashboard')


def portal_template_use(request, pk):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    template = get_object_or_404(OrderTemplate, pk=pk, customer=customer)
    new_order = CustomerOrder.objects.create(
        customer=customer, status='received', payment_status='unpaid',
    )
    items_payload = []
    for raw in template.snapshot.get('items', []):
        item = OrderItem.objects.create(
            order=new_order, garment_type=raw.get('garment_type', 'Garment'),
            fabric=raw.get('fabric', ''), color=raw.get('color', ''),
            size_label=raw.get('size_label', ''),
            quantity=int(raw.get('quantity', 1) or 1),
            special_instructions=raw.get('special_instructions', ''),
        )
        for m in raw.get('measurements', []):
            try:
                Measurement.objects.create(
                    order_item=item, measurement_type=m['type'],
                    measurement_value=Decimal(m['value']), unit=m.get('unit', 'cm'),
                )
            except Exception:
                continue
        items_payload.append({
            'garment_type': item.garment_type, 'fabric': item.fabric,
            'priority': new_order.priority, 'quantity': item.quantity,
        })
    quote = pricing_service.quote_order(customer=customer, items=items_payload)
    pricing_service.freeze_onto_order(new_order, quote)
    messages.success(request, f'Order #{new_order.pk} created from template "{template.name}".')
    return redirect('portal_order_detail', pk=new_order.pk)


def portal_appointments(request):
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    appointments = customer.appointments.order_by('scheduled_at')
    local_now = timezone.localtime()
    first_bookable_day = local_now.date() + timedelta(
        days=django_settings.APPOINTMENT_MIN_DAYS_AHEAD,
    )
    appointment_min_local = timezone.make_aware(
        datetime.combine(
            first_bookable_day,
            time(hour=django_settings.APPOINTMENT_START_HOUR),
        ),
        timezone.get_current_timezone(),
    )
    if request.method == 'POST':
        kind = request.POST.get('kind', 'fitting')
        when_str = request.POST.get('scheduled_at', '')
        notes = request.POST.get('notes', '')
        try:
            when = timezone.datetime.fromisoformat(when_str)
            if timezone.is_naive(when):
                when = timezone.make_aware(when, timezone.get_current_timezone())
        except Exception:
            messages.error(request, _('Please pick a valid date and time.'))
            return redirect('portal_appointments')
        local_when = timezone.localtime(when)
        if local_when.date() <= local_now.date():
            messages.error(request, _('Appointments must be on a future day, not today or earlier.'))
            return redirect('portal_appointments')
        if local_when.weekday() not in django_settings.APPOINTMENT_ALLOWED_WEEKDAYS:
            messages.error(request, _('Appointments are only available on weekdays.'))
            return redirect('portal_appointments')
        hour = local_when.hour
        if hour < django_settings.APPOINTMENT_START_HOUR:
            messages.error(request, _('That time is before the workshop opens.'))
            return redirect('portal_appointments')
        if hour >= django_settings.APPOINTMENT_END_HOUR_EXCLUSIVE:
            messages.error(request, _('That time is after the workshop closes.'))
            return redirect('portal_appointments')
        appt = Appointment.objects.create(
            customer=customer, kind=kind, scheduled_at=when, notes=notes,
        )
        events.emit(events.APPOINTMENT_REQUESTED, target=appt, actor=request.user, payload={
            'kind': appt.get_kind_display(),
        })
        audit.log(actor=request.user, action='appointment.requested', target=appt,
                  before={}, after={'kind': kind})
        messages.success(request, _('Your appointment request was submitted.'))
        return redirect('portal_appointments')
    return render(request, 'portal/appointments.html', {
        'appointments': appointments,
        'customer': customer,
        'appointment_min_local': appointment_min_local,
        'appointment_end_hour': django_settings.APPOINTMENT_END_HOUR_EXCLUSIVE,
    })


# ────────────────────────────────────────────────────────────────────────
#  Public intake form
# ────────────────────────────────────────────────────────────────────────


def public_intake(request):
    if request.method == 'POST':
        if request.POST.get('hp', ''):
            return redirect('public_intake')
        lead = Lead.objects.create(
            name=request.POST.get('name', '').strip()[:160],
            email=request.POST.get('email', '').strip(),
            phone=request.POST.get('phone', '').strip(),
            garment_type=request.POST.get('garment_type', '').strip()[:120] or 'Unspecified',
            fabric=request.POST.get('fabric', '').strip(),
            color=request.POST.get('color', '').strip(),
            due_date=request.POST.get('due_date') or None,
            notes=request.POST.get('notes', '').strip(),
            language=request.POST.get('language', 'es'),
        )
        if 'reference_image' in request.FILES:
            Attachment.objects.create(
                content_type=ContentType.objects.get_for_model(Lead),
                object_id=lead.pk,
                file=request.FILES['reference_image'],
                kind='intake',
                caption='Intake reference',
            )
        events.emit(events.LEAD_RECEIVED, target=lead, actor=None, payload={'lead_id': lead.pk})
        return render(request, 'portal/intake_thanks.html', {'lead': lead})
    return render(request, 'portal/intake.html', {})


# ────────────────────────────────────────────────────────────────────────
#  Staff: leads inbox + conversion
# ────────────────────────────────────────────────────────────────────────


@login_required
def lead_list(request):
    leads = Lead.objects.order_by('-created_at')
    return render(request, 'shop/lead_list.html', {'leads': leads})


@login_required
@require_POST
def lead_convert(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    try:
        order = intake_service.convert_lead(lead, actor=request.user)
        messages.success(request, f'Lead converted to order #{order.pk}.')
        return redirect('order_detail', pk=order.pk)
    except Exception as exc:
        messages.error(request, f'Could not convert lead: {exc}')
    return redirect('lead_list')


# ────────────────────────────────────────────────────────────────────────
#  Staff: inventory + materials + supplier orders + material requests
# ────────────────────────────────────────────────────────────────────────


@login_required
def material_list(request):
    q = request.GET.get('q', '')
    category = request.GET.get('category', '')
    materials = Material.objects.select_related('supplier', 'location')
    if q:
        materials = materials.filter(
            Q(name__icontains=q) | Q(color__icontains=q) | Q(supplier__name__icontains=q)
        )
    if category:
        materials = materials.filter(category=category)
    materials = list(materials.order_by('name'))
    for m in materials:
        m.usage_count_value = m.usage_count
    return render(request, 'shop/material_list.html', {
        'materials': materials, 'q': q, 'category': category,
        'category_choices': Material.CATEGORY_CHOICES,
    })


@login_required
def material_create(request):
    return _material_form(request, instance=None, title='Add Material')


@login_required
def material_edit(request, pk):
    return _material_form(request, instance=get_object_or_404(Material, pk=pk),
                           title='Edit Material')


def _material_form(request, *, instance, title):
    from django import forms

    class _MaterialForm(forms.ModelForm):
        class Meta:
            model = Material
            fields = ['name', 'category', 'color', 'default_unit',
                      'unit_cost', 'supplier', 'stock_on_hand',
                      'low_stock_threshold', 'location', 'is_active', 'notes']
            widgets = {
                'name': forms.TextInput(attrs={'class': 'form-control'}),
                'color': forms.TextInput(attrs={'class': 'form-control'}),
                'category': forms.Select(attrs={'class': 'form-select'}),
                'default_unit': forms.Select(attrs={'class': 'form-select'}),
                'unit_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
                'supplier': forms.Select(attrs={'class': 'form-select'}),
                'stock_on_hand': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
                'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
                'location': forms.TextInput(attrs={'class': 'form-control'}),
                'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
                'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            }

    if request.method == 'POST':
        form = _MaterialForm(request.POST, instance=instance)
        if form.is_valid():
            mat = form.save()
            audit.log(actor=request.user, action='material.saved', target=mat,
                      before={}, after={'name': mat.name})
            messages.success(request, f'Saved material "{mat.name}".')
            return redirect('material_list')
    else:
        form = _MaterialForm(instance=instance)
    return render(request, 'shop/material_form.html', {
        'form': form, 'title': title, 'material': instance,
    })


@login_required
def inventory_dashboard(request):
    materials = list(Material.objects.select_related('supplier').order_by('name'))
    low = [m for m in materials if m.is_low_stock]
    suppliers = Supplier.objects.filter(is_active=True)
    pending_orders = SupplierOrder.objects.exclude(status__in=['received', 'cancelled'])
    return render(request, 'shop/inventory.html', {
        'materials': materials, 'low_stock': low, 'suppliers': suppliers,
        'pending_orders': pending_orders,
    })


@login_required
@require_POST
def supplier_order_create(request):
    supplier_id = request.POST.get('supplier')
    material_id = request.POST.get('material')
    quantity = request.POST.get('quantity', '1')
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    material = get_object_or_404(Material, pk=material_id)
    so = SupplierOrder.objects.create(
        supplier=supplier, status='draft',
        created_by=request.user,
    )
    SupplierOrderLine.objects.create(
        supplier_order=so, material=material,
        quantity=Decimal(quantity), unit_cost=material.unit_cost,
    )
    so.recalculate_total()
    audit.log(actor=request.user, action='supplier_order.created', target=so,
              before={}, after={'supplier_id': supplier.pk, 'total': str(so.total)})
    messages.success(request, f'Draft supplier order #{so.pk} created for {supplier.name}.')
    return redirect('supplier_order_detail', pk=so.pk)


@login_required
def supplier_order_detail(request, pk):
    so = get_object_or_404(SupplierOrder, pk=pk)
    return render(request, 'shop/supplier_order_detail.html', {
        'supplier_order': so,
        'next_states': workflow.next_states(so),
    })


@login_required
@require_POST
def supplier_order_transition(request, pk):
    so = get_object_or_404(SupplierOrder, pk=pk)
    target = request.POST.get('to')
    try:
        if target == 'received':
            inventory_service.receive_supplier_order(so, actor=request.user)
            messages.success(request, f'Supplier order #{so.pk} received and stock updated.')
        else:
            workflow.transition(so, to=target, actor=request.user)
            messages.success(request, f'Supplier order #{so.pk} → {so.get_status_display()}.')
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect('supplier_order_detail', pk=so.pk)


@login_required
def material_request_list(request):
    requests = MaterialRequest.objects.select_related(
        'material', 'requested_by', 'supplier_order'
    ).order_by('-created_at')
    return render(request, 'shop/material_request_list.html', {
        'requests': requests,
    })


@login_required
@require_POST
def material_request_decision(request, pk):
    req = get_object_or_404(MaterialRequest, pk=pk)
    target = request.POST.get('to')
    comment = request.POST.get('comment', '')
    try:
        if target == 'converted':
            so = inventory_service.create_supplier_order_from_request(req, actor=request.user)
            workflow.transition_request(req, to='converted', actor=request.user,
                                          comment=comment, supplier_order=so)
            messages.success(request, f'Request converted to supplier order #{so.pk}.')
            return redirect('supplier_order_detail', pk=so.pk)
        workflow.transition_request(req, to=target, actor=request.user, comment=comment)
        messages.success(request, f'Request {req.pk} → {req.get_status_display()}.')
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect('material_request_list')


# ────────────────────────────────────────────────────────────────────────
#  Staff: pricing dashboard (UX wrapper around admin)
# ────────────────────────────────────────────────────────────────────────


@login_required
def pricing_dashboard(request):
    models_mod = __import__('shop.models', fromlist=['FabricType', 'AddOn', 'UrgencySurcharge'])
    return render(request, 'shop/pricing.html', {
        'categories': GarmentCategory.objects.order_by('name'),
        'fabrics': models_mod.FabricType.objects.order_by('name'),
        'addons': models_mod.AddOn.objects.order_by('name'),
        'urgencies': models_mod.UrgencySurcharge.objects.all(),
        'discount_rules': DiscountRule.objects.order_by('code'),
        'currencies': Currency.objects.order_by('code'),
        'rates': ExchangeRate.objects.select_related('currency').order_by('-captured_on')[:20],
    })


# ────────────────────────────────────────────────────────────────────────
#  Notifications, search, calendar
# ────────────────────────────────────────────────────────────────────────


@login_required
def notifications_view(request):
    notif_qs = NotificationLog.objects.filter(
        Q(user=request.user) | Q(channel='inapp', recipient=request.user.username)
    )
    if request.method == 'POST':
        notif_qs.filter(is_read=False).update(is_read=True)
        messages.success(request, _('All notifications marked as read.'))
        return redirect('notifications')
    rows = notif_qs.order_by('-created_at')[:80]
    return render(request, 'shop/notifications.html', {'rows': rows})


@login_required
@require_POST
def set_display_currency(request):
    code = (request.POST.get('currency') or '').strip().upper()[:3]
    if code and Currency.objects.filter(code=code).exists():
        request.session[display_currency_service.SESSION_KEY_DISPLAY_CURRENCY] = code
    next_url = (request.POST.get('next') or '').strip()
    if not next_url:
        if Customer.objects.filter(user=request.user).exists() and not request.user.is_staff:
            next_url = reverse('portal_dashboard')
        elif Employee.objects.filter(user=request.user).exists():
            next_url = reverse('emp_dashboard')
        else:
            next_url = reverse('dashboard')
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if Employee.objects.filter(user=request.user).exists():
        return redirect('emp_dashboard')
    if Customer.objects.filter(user=request.user).exists():
        return redirect('portal_dashboard')
    return redirect('dashboard')


@login_required
def search_view(request):
    q = (request.GET.get('q') or '').strip()
    customers = orders = tickets = materials = leads = []
    if q:
        customers = Customer.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(email__icontains=q) | Q(phone__icontains=q)
        )[:10]
        orders = CustomerOrder.objects.filter(
            Q(notes__icontains=q) | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q) | Q(pk__iexact=q if q.isdigit() else 0)
        ).select_related('customer')[:10]
        tickets = WorkTicket.objects.filter(
            Q(ticket_code__icontains=q) | Q(design_notes__icontains=q)
            | Q(observations__icontains=q)
        )[:10]
        materials = Material.objects.filter(
            Q(name__icontains=q) | Q(color__icontains=q)
        )[:10]
        leads = Lead.objects.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(notes__icontains=q)
        )[:10]
    return render(request, 'shop/search.html', {
        'q': q, 'customers': customers, 'orders': orders,
        'tickets': tickets, 'materials': materials, 'leads': leads,
    })


@login_required
def calendar_view(request):
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    weeks = monthcalendar(year, month)
    orders = CustomerOrder.objects.filter(
        due_date__year=year, due_date__month=month
    ).exclude(status__in=['delivered', 'cancelled']).select_related('customer')
    tickets = WorkTicket.objects.filter(
        deadline__year=year, deadline__month=month
    ).exclude(status__in=['completed', 'cancelled']).select_related('order_item__order__customer')
    appointments = Appointment.objects.filter(
        scheduled_at__year=year, scheduled_at__month=month
    ).exclude(status__in=['cancelled', 'no_show']).select_related('customer')
    by_day = {}
    for o in orders:
        by_day.setdefault(o.due_date.day, []).append(('order', o))
    for t in tickets:
        if t.deadline:
            by_day.setdefault(t.deadline.day, []).append(('ticket', t))
    for a in appointments:
        by_day.setdefault(a.scheduled_at.day, []).append(('appt', a))
    return render(request, 'shop/calendar.html', {
        'year': year, 'month': month, 'weeks': weeks,
        'today': today, 'by_day': by_day,
    })


# ────────────────────────────────────────────────────────────────────────
#  Receipts and invoices
# ────────────────────────────────────────────────────────────────────────


@login_required
def order_invoice(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    language = request.GET.get('lang') or (order.customer.language if order.customer else 'es')
    html = documents.render_invoice_html(order, language=language)
    return HttpResponse(html)


def _portal_owns_order(request, pk):
    if not request.user.is_authenticated:
        return None
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return None
    return CustomerOrder.objects.filter(pk=pk, customer=customer).first()


def portal_invoice(request, pk):
    order = CustomerOrder.objects.filter(pk=pk).first() if request.user.is_staff else _portal_owns_order(request, pk)
    if order is None:
        return redirect('portal_login')
    language = request.GET.get('lang') or (order.customer.language if order.customer else 'es')
    return HttpResponse(documents.render_invoice_html(order, language=language))


def portal_payment_receipt(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id)
    if not request.user.is_staff:
        if not request.user.is_authenticated or payment.order.customer.user_id != request.user.id:
            return redirect('portal_login')
    language = request.GET.get('lang') or (payment.order.customer.language if payment.order.customer else 'es')
    display_code = display_currency_service.resolve_display_currency_code(request)
    return HttpResponse(documents.render_receipt_html(
        payment,
        language=language,
        display_currency_code=display_code,
    ))


# ────────────────────────────────────────────────────────────────────────
#  Attachments (shared upload endpoint)
# ────────────────────────────────────────────────────────────────────────


_ATTACH_MAP = {
    'order': CustomerOrder,
    'item': OrderItem,
    'ticket': WorkTicket,
    'lead': Lead,
}


@login_required
@require_POST
def attachment_upload(request, kind, target_kind, target_pk):
    model = _ATTACH_MAP.get(target_kind)
    if model is None or 'file' not in request.FILES:
        raise Http404
    target = get_object_or_404(model, pk=target_pk)
    # Non-staff (customers) may only upload onto their own orders/items.
    # Employees may upload to tickets even if they aren't Django staff.
    is_employee = Employee.objects.filter(user=request.user).exists()
    if not request.user.is_staff and not is_employee:
        try:
            customer = Customer.objects.get(user=request.user)
        except Customer.DoesNotExist:
            raise Http404
        if isinstance(target, CustomerOrder) and target.customer_id != customer.pk:
            raise Http404
        if isinstance(target, OrderItem) and target.order.customer_id != customer.pk:
            raise Http404
        if isinstance(target, WorkTicket):
            raise Http404
    Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(model),
        object_id=target.pk,
        file=request.FILES['file'],
        kind=kind,
        caption=request.POST.get('caption', '')[:200],
        uploaded_by=request.user,
    )
    audit.log(actor=request.user, action='attachment.uploaded', target=target,
              before={}, after={'kind': kind, 'filename': request.FILES['file'].name})
    if request.headers.get('Referer'):
        return redirect(request.headers['Referer'])
    return JsonResponse({'ok': True})


# ────────────────────────────────────────────────────────────────────────
#  Employee portal
# ────────────────────────────────────────────────────────────────────────


def emp_login(request):
    if request.user.is_authenticated:
        emp = _get_employee(request)
        if emp:
            return redirect('emp_dashboard')
        if request.user.is_staff:
            return redirect('dashboard')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        user = _authenticate_by_email_or_username(request, email, password)
        if user:
            emp = Employee.objects.filter(user=user).first()
            if emp:
                login(request, user)
                return redirect('emp_dashboard')
            if user.is_staff:
                login(request, user)
                return redirect('dashboard')
            return render(request, 'employee/login.html', {
                'error': 'No employee account linked to this user.',
                'email': email,
            })
        return render(request, 'employee/login.html', {
            'error': 'Invalid email or password.',
            'email': email,
        })
    return render(request, 'employee/login.html')


def emp_logout(request):
    logout(request)
    return redirect('emp_login')


@emp_required
def emp_dashboard(request, employee):
    today = timezone.now().date()
    my_assignments = TaskAssignment.objects.filter(
        employee=employee, assignment_status='current'
    ).values_list('ticket_id', flat=True)
    my_tickets_qs = WorkTicket.objects.filter(
        pk__in=my_assignments
    ).exclude(status='completed').select_related(
        'current_stage', 'order_item__order__customer'
    ).order_by('priority', 'deadline')[:10]
    my_open = WorkTicket.objects.filter(pk__in=my_assignments).exclude(status='completed').count()
    my_urgent = WorkTicket.objects.filter(pk__in=my_assignments, priority='urgent').exclude(status='completed').count()
    my_done_today = TicketStatusHistory.objects.filter(
        ticket__in=my_assignments, changed_at__date=today,
        stage__stage_name__icontains='quality',
    ).count()
    shop_overdue = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).count()
    pipeline = ProductionStage.objects.annotate(
        ticket_count=Count('active_tickets', filter=Q(
            active_tickets__status__in=['open', 'assigned', 'in_progress']
        ))
    ).order_by('stage_order')
    my_requests = MaterialRequest.objects.filter(
        requested_by=employee
    ).order_by('-created_at')[:5]
    return render(request, 'employee/dashboard.html', {
        'employee': employee, 'my_tickets': my_tickets_qs,
        'my_open': my_open, 'my_urgent': my_urgent,
        'my_done_today': my_done_today, 'shop_overdue': shop_overdue,
        'pipeline': pipeline, 'my_requests': my_requests,
        'materials': Material.objects.filter(is_active=True).order_by('name'),
    })


@emp_required
def emp_my_tickets(request, employee):
    my_assignments = TaskAssignment.objects.filter(
        employee=employee, assignment_status='current'
    ).values_list('ticket_id', flat=True)
    tickets = WorkTicket.objects.filter(
        pk__in=my_assignments
    ).select_related('current_stage', 'order_item__order__customer').order_by('priority', 'deadline')
    return render(request, 'employee/my_tickets.html', {
        'employee': employee, 'tickets': tickets,
    })


@emp_required
def emp_all_tickets(request, employee):
    tickets = WorkTicket.objects.select_related(
        'current_stage', 'order_item__order__customer'
    ).prefetch_related('assignments__employee')
    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    if priority_filter:
        tickets = tickets.filter(priority=priority_filter)
    tickets = tickets.order_by('priority', 'deadline')
    return render(request, 'employee/all_tickets.html', {
        'employee': employee, 'tickets': tickets,
    })


@emp_required
def emp_ticket_detail(request, pk, employee):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    history = ticket.status_history.select_related('stage', 'changed_by').order_by('changed_at')
    stages = ProductionStage.objects.order_by('stage_order')
    incidents = ticket.damage_incidents.all()
    qr_data_url = qr_service.qr_png_data_url(ticket.qr_payload)
    return render(request, 'employee/ticket_detail.html', {
        'employee': employee, 'ticket': ticket, 'history': history,
        'stages': stages, 'incidents': incidents,
        'next_states': workflow.next_states(ticket),
        'attachments': ticket.attachments.all(),
        'qr_data_url': qr_data_url,
    })


@emp_required
@require_POST
def emp_update_stage(request, pk, employee):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    stage_id = request.POST.get('stage')
    comment = request.POST.get('comment', '').strip()
    try:
        stage = ProductionStage.objects.get(pk=stage_id)
        workflow.advance_stage(
            ticket, to_stage=stage, actor=request.user,
            comment=comment or f'Stage updated by {employee.full_name}',
            force_skip=False,
        )
        messages.success(request, f'Stage updated to "{stage.stage_name}".')
    except (ProductionStage.DoesNotExist, workflow.WorkflowError) as exc:
        messages.error(request, str(exc) or 'Invalid stage selected.')
    return redirect('emp_ticket_detail', pk=pk)


@emp_required
@require_POST
def emp_complete_ticket(request, pk, employee):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    comment = request.POST.get('comment', '').strip()
    last_stage = ProductionStage.objects.order_by('-stage_order').first()
    if last_stage:
        try:
            workflow.advance_stage(
                ticket,
                to_stage=last_stage,
                actor=request.user,
                comment='Final stage on completion',
                force_skip=True,
            )
        except workflow.WorkflowError:
            pass
    try:
        workflow.transition(ticket, to='completed', actor=request.user,
                             comment=comment or f'Completed by {employee.full_name}')
        messages.success(request, f'Ticket {ticket.ticket_code} marked as completed.')
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect('emp_my_tickets')


@emp_required
def emp_orders(request, employee):
    orders = CustomerOrder.objects.exclude(
        status__in=['delivered', 'cancelled']
    ).select_related('customer').order_by('due_date')
    return render(request, 'employee/orders.html', {
        'employee': employee, 'orders': orders,
    })


@emp_required
def emp_profile(request, employee):
    return render(request, 'employee/profile.html', {'employee': employee})


@emp_required
def emp_request_create(request, employee):
    materials = Material.objects.filter(is_active=True).order_by('name')
    if request.method == 'POST':
        material_id = request.POST.get('material')
        quantity = request.POST.get('quantity', '1')
        priority = request.POST.get('priority', 'normal')
        reason = request.POST.get('reason', '').strip()
        if not (material_id and reason):
            messages.error(request, 'Please pick a material and explain the reason.')
            return redirect('emp_request_create')
        material = get_object_or_404(Material, pk=material_id)
        req = MaterialRequest.objects.create(
            requested_by=employee, material=material,
            quantity=Decimal(quantity), priority=priority, reason=reason,
        )
        audit.log(actor=request.user, action='materialrequest.created', target=req,
                  before={}, after={'material_id': material.pk, 'quantity': str(quantity)})
        events.emit(events.MATERIAL_REQUESTED, target=req, actor=request.user, payload={})
        messages.success(request, 'Request submitted.')
        return redirect('emp_dashboard')
    return render(request, 'employee/request_form.html', {
        'employee': employee, 'materials': materials,
        'priority_choices': MaterialRequest.PRIORITY_CHOICES,
    })


@emp_required
def emp_scan(request, employee):
    code = (request.GET.get('code') or '').strip()
    ticket = None
    if code:
        # Accept either raw ticket code (TKT-00001) or the QR payload (CDP-TICKET:TKT-00001)
        if ':' in code:
            code = code.split(':')[-1]
        ticket = WorkTicket.objects.filter(ticket_code__iexact=code).first()
        if ticket:
            return redirect('emp_ticket_detail', pk=ticket.pk)
        messages.error(request, f'No ticket matches code "{code}".')
    return render(request, 'employee/scan.html', {'employee': employee, 'code': code})
