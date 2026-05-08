from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from decimal import Decimal
from datetime import timedelta
from calendar import monthcalendar
import json
from pathlib import Path

from .models import (
    Customer, CustomerOrder, OrderItem, Measurement,
    WorkTicket, TaskAssignment, TicketStatusHistory,
    DamageIncident, Payment, Delivery, Employee, ProductionStage
)
from .forms import (
    CustomerForm, CustomerOrderForm, OrderItemForm, MeasurementForm,
    WorkTicketForm, TicketStatusUpdateForm, TaskAssignmentForm,
    DamageIncidentForm, PaymentForm, DeliveryForm
)


# region agent log
DEBUG_LOG_PATH = Path(
    '/Users/salomeshioshvili/Downloads/sewingshop 3/.cursor/debug-a94f13.log'
)
DEBUG_SESSION_ID = 'a94f13'


def _append_debug_log(run_id, hypothesis_id, location, message, data):
    payload = {
        'sessionId': DEBUG_SESSION_ID,
        'runId': run_id,
        'hypothesisId': hypothesis_id,
        'location': location,
        'message': message,
        'data': data,
        'timestamp': int(timezone.now().timestamp() * 1000),
    }
    try:
        with DEBUG_LOG_PATH.open('a', encoding='utf-8') as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=True) + '\n')
    except OSError:
        return
# endregion


@login_required
def dashboard(request):
    today = timezone.now().date()

    # Order stats
    total_orders = CustomerOrder.objects.count()
    pending_orders = CustomerOrder.objects.filter(status__in=['draft', 'received']).count()
    in_production = CustomerOrder.objects.filter(status='in_production').count()
    completed_orders = CustomerOrder.objects.filter(status='completed').count()
    delivered_orders = CustomerOrder.objects.filter(status='delivered').count()
    overdue_orders = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).count()

    # Ticket stats
    open_tickets = WorkTicket.objects.filter(status__in=['open', 'assigned', 'in_progress']).count()
    overdue_tickets = WorkTicket.objects.filter(
        deadline__lt=today
    ).exclude(status__in=['completed', 'cancelled']).count()
    blocked_tickets = WorkTicket.objects.filter(status='blocked').count()

    # Recent orders
    recent_orders = CustomerOrder.objects.select_related('customer').order_by('-created_at')[:8]

    # Urgent tickets
    urgent_tickets = WorkTicket.objects.filter(
        priority__in=['high', 'urgent']
    ).exclude(status__in=['completed', 'cancelled']).select_related(
        'order_item__order__customer', 'current_stage'
    ).order_by('-priority', 'deadline')[:6]

    # Unresolved damage incidents
    damage_count = DamageIncident.objects.filter(is_resolved=False).count()

    # Orders due soon (next 3 days)
    due_soon = CustomerOrder.objects.filter(
        due_date__range=[today, today + timedelta(days=3)]
    ).exclude(status__in=['delivered', 'cancelled']).select_related('customer').count()

    # Stage distribution for chart
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
        .select_related('customer')
        .order_by('due_date')[:5]
    ):
        rail_items.append(
            {
                'date': o.due_date,
                'title': f'Order #{o.pk}',
                'sub': o.customer.full_name,
                'url': 'order_detail',
                'pk': o.pk,
            }
        )
    for t in (
        WorkTicket.objects.filter(deadline__gte=today, deadline__lte=rail_end)
        .exclude(status__in=['completed', 'cancelled'])
        .select_related('order_item__order__customer')[:5]
    ):
        rail_items.append(
            {
                'date': t.deadline,
                'title': t.ticket_code,
                'sub': t.order_item.order.customer.full_name,
                'url': 'ticket_detail',
                'pk': t.pk,
            }
        )
    rail_items.sort(key=lambda x: x['date'])

    highlight_order = recent_orders[0] if recent_orders else None

    context = {
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'in_production': in_production,
        'completed_orders': completed_orders,
        'delivered_orders': delivered_orders,
        'overdue_orders': overdue_orders,
        'overdue_ids': overdue_ids,
        'open_tickets': open_tickets,
        'overdue_tickets': overdue_tickets,
        'blocked_tickets': blocked_tickets,
        'damage_count': damage_count,
        'due_soon': due_soon,
        'recent_orders': recent_orders,
        'urgent_tickets': urgent_tickets,
        'stages': stages,
        'today': today,
        'cal_weeks': cal_weeks,
        'cal_heading': cal_heading,
        'cal_month': cal_month,
        'cal_year': cal_year,
        'due_day_numbers': due_day_numbers,
        'rail_items': rail_items,
        'highlight_order': highlight_order,
    }
    return render(request, 'shop/dashboard.html', context)


@login_required
def customer_list(request):
    q = request.GET.get('q', '')
    customers = Customer.objects.annotate(order_count=Count('orders'))
    if q:
        customers = customers.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(phone__icontains=q) | Q(email__icontains=q)
        )
    return render(request, 'shop/customer_list.html', {'customers': customers, 'q': q})


@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
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
            form.save()
            messages.success(request, 'Customer updated successfully.')
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'shop/customer_form.html', {
        'form': form, 'customer': customer, 'title': f'Edit {customer.full_name}'
    })


@login_required
def order_list(request):
    status_filter = request.GET.get('status', '')
    priority_filter = request.GET.get('priority', '')
    q = request.GET.get('q', '')
    today = timezone.now().date()

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
    # region agent log
    debug_run_id = request.GET.get('debug_run_id', 'initial')
    preview_orders = []
    for order in orders.order_by('-created_at')[:5]:
        preview_orders.append({
            'orderId': order.pk,
            'finalAmount': str(order.final_amount),
            'subtotal': str(order.subtotal_amount),
            'itemCount': order.items.count(),
            'status': order.status,
        })
    _append_debug_log(
        run_id=debug_run_id,
        hypothesis_id='H3_admin_page_without_price_field',
        location='shop/views.py:order_list',
        message='Admin order list pricing preview',
        data={
            'query': q,
            'statusFilter': status_filter,
            'priorityFilter': priority_filter,
            'resultCount': orders.count(),
            'previewOrders': preview_orders,
        },
    )
    # endregion

    context = {
        'orders': orders.order_by('-created_at'),
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'q': q,
        'overdue_ids': overdue_ids,
        'status_choices': CustomerOrder.STATUS_CHOICES,
        'priority_choices': CustomerOrder.PRIORITY_CHOICES,
    }
    return render(request, 'shop/order_list.html', context)


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
            messages.success(request, f'Order #{order.pk} created. Now add garment items.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(initial=initial)
    return render(request, 'shop/order_form.html', {'form': form, 'title': 'Create New Order'})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    items = order.items.prefetch_related('measurements', 'tickets', 'damage_incidents')
    payments = order.payments.all()
    delivery = getattr(order, 'delivery', None)
    total_paid = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    remaining_balance = order.final_amount - total_paid
    credit_amount = Decimal('0.00')
    if remaining_balance < Decimal('0.00'):
        credit_amount = abs(remaining_balance)
    # region agent log
    debug_run_id = request.GET.get('debug_run_id', 'initial')
    _append_debug_log(
        run_id=debug_run_id,
        hypothesis_id='H1_admin_price_missing_in_context',
        location='shop/views.py:order_detail',
        message='Admin order detail pricing context',
        data={
            'orderId': order.pk,
            'subtotal': str(order.subtotal_amount),
            'finalAmount': str(order.final_amount),
            'paymentStatus': order.payment_status,
            'totalPaid': str(total_paid),
            'itemCount': items.count(),
        },
    )
    # endregion

    context = {
        'order': order,
        'items': items,
        'payments': payments,
        'delivery': delivery,
        'total_paid': total_paid,
        'balance': remaining_balance,
        'credit_amount': credit_amount,
        'today': timezone.now().date(),
    }
    return render(request, 'shop/order_detail.html', context)


@login_required
def order_edit(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    if request.method == 'POST':
        form = CustomerOrderForm(request.POST, instance=order)
        if form.is_valid():
            order = form.save()
            order.recalculate_amounts()
            messages.success(request, f'Order #{order.pk} updated.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(instance=order)
    return render(request, 'shop/order_form.html', {
        'form': form, 'order': order, 'title': f'Edit Order #{order.pk}'
    })


@login_required
def order_status_update(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    new_status = request.POST.get('status')
    if new_status and new_status in dict(CustomerOrder.STATUS_CHOICES):
        order.status = new_status
        order.save(update_fields=['status'])
        messages.success(request, f'Order status updated to {order.get_status_display()}.')
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
            order.recalculate_amounts()
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
            item.order.recalculate_amounts()
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
            Q(ticket_code__icontains=q) |
            Q(order_item__garment_type__icontains=q) |
            Q(order_item__order__customer__first_name__icontains=q) |
            Q(order_item__order__customer__last_name__icontains=q)
        )

    context = {
        'tickets': tickets.order_by('-created_at'),
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'stage_filter': stage_filter,
        'q': q,
        'stages': ProductionStage.objects.all(),
        'status_choices': WorkTicket.TICKET_STATUS_CHOICES,
        'priority_choices': WorkTicket.PRIORITY_CHOICES,
        'today': today,
    }
    return render(request, 'shop/ticket_list.html', context)


@login_required
def ticket_create(request, item_pk=None):
    initial = {}
    order_item = None
    if item_pk:
        order_item = get_object_or_404(OrderItem, pk=item_pk)
        initial['order_item'] = order_item

    first_stage = ProductionStage.objects.order_by('stage_order').first()
    if first_stage:
        initial['current_stage'] = first_stage

    if request.method == 'POST':
        form = WorkTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save()
            # Record initial status history
            TicketStatusHistory.objects.create(
                ticket=ticket,
                stage=ticket.current_stage,
                comment='Ticket created.'
            )
            # Update order item status
            ticket.order_item.item_status = 'in_progress'
            ticket.order_item.save(update_fields=['item_status'])
            # Update order status
            order = ticket.order_item.order
            if order.status == 'received':
                order.status = 'in_production'
                order.save(update_fields=['status'])
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

    context = {
        'ticket': ticket,
        'history': history,
        'assignments': assignments,
        'incidents': incidents,
        'update_form': update_form,
        'assign_form': assign_form,
        'today': timezone.now().date(),
    }
    return render(request, 'shop/ticket_detail.html', context)


@login_required
def ticket_update_stage(request, pk):
    """Workflow 2: Update ticket production stage."""
    ticket = get_object_or_404(WorkTicket, pk=pk)
    if request.method == 'POST':
        form = TicketStatusUpdateForm(request.POST)
        if form.is_valid():
            stage = form.cleaned_data['stage']
            new_status = form.cleaned_data['status']
            changed_by = form.cleaned_data.get('changed_by')
            comment = form.cleaned_data.get('comment', '')

            # Update ticket
            ticket.current_stage = stage
            ticket.status = new_status
            ticket.save(update_fields=['current_stage', 'status', 'updated_at'])

            # Record history
            TicketStatusHistory.objects.create(
                ticket=ticket,
                stage=stage,
                changed_by=changed_by,
                comment=comment
            )

            # If completed, update order item
            if new_status == 'completed':
                item = ticket.order_item
                # Check if all tickets for this item are done
                all_done = not item.tickets.exclude(
                    status__in=['completed', 'cancelled']
                ).exists()
                if all_done:
                    item.item_status = 'completed'
                    item.save(update_fields=['item_status'])
                    # Check if all items are done
                    order = item.order
                    all_items_done = not order.items.exclude(
                        item_status__in=['completed', 'cancelled', 'delivered']
                    ).exists()
                    if all_items_done:
                        order.status = 'completed'
                        order.save(update_fields=['status'])

            messages.success(request, f'Ticket moved to stage: {stage.stage_name}')
    return redirect('ticket_detail', pk=ticket.pk)


@login_required
def ticket_assign(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    if request.method == 'POST':
        form = TaskAssignmentForm(request.POST)
        if form.is_valid():
            # Close current assignment
            ticket.assignments.filter(assignment_status='current').update(
                assignment_status='reassigned',
                unassigned_at=timezone.now()
            )
            assignment = form.save(commit=False)
            assignment.ticket = ticket
            assignment.assignment_status = 'current'
            assignment.save()

            ticket.status = 'assigned'
            ticket.save(update_fields=['status'])

            messages.success(request, f'Ticket assigned to {assignment.employee.full_name}.')
    return redirect('ticket_detail', pk=pk)


@login_required
def damage_incident_create(request, ticket_pk):
    ticket = get_object_or_404(WorkTicket, pk=ticket_pk)
    if request.method == 'POST':
        form = DamageIncidentForm(request.POST)
        if form.is_valid():
            incident = form.save(commit=False)
            incident.ticket = ticket
            incident.order_item = ticket.order_item
            incident.save()
            # Update item status
            ticket.order_item.item_status = 'damaged'
            ticket.order_item.save(update_fields=['item_status'])
            # Block ticket
            ticket.status = 'blocked'
            ticket.save(update_fields=['status'])
            messages.warning(request, 'Damage incident recorded. Ticket blocked pending resolution.')
    return redirect('ticket_detail', pk=ticket_pk)


@login_required
def damage_incident_resolve(request, pk):
    incident = get_object_or_404(DamageIncident, pk=pk)
    if request.method == 'POST':
        incident.is_resolved = True
        incident.resolution_action = request.POST.get('resolution_action', incident.resolution_action)
        incident.resolution_notes = request.POST.get('resolution_notes', '')
        incident.save()
        # Unblock ticket if no more unresolved incidents
        ticket = incident.ticket
        if not ticket.damage_incidents.filter(is_resolved=False).exists():
            ticket.status = 'in_progress'
            ticket.save(update_fields=['status'])
        messages.success(request, 'Incident resolved.')
    return redirect('ticket_detail', pk=incident.ticket.pk)


@login_required
def payment_add(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.order = order
            payment.recorded_by = request.user
            payment.save()
            # Update payment status
            total_paid = order.payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
            if total_paid >= order.final_amount:
                order.payment_status = 'paid'
            elif total_paid > 0:
                order.payment_status = 'partially_paid'
            order.save(update_fields=['payment_status'])
            messages.success(request, f'Payment of ${payment.amount} recorded.')
    return redirect('order_detail', pk=order_pk)


@login_required
def delivery_create(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method == 'POST':
        form = DeliveryForm(request.POST)
        if form.is_valid():
            delivery = form.save(commit=False)
            delivery.order = order
            delivery.save()
            if delivery.is_delivered:
                order.status = 'delivered'
                order.save(update_fields=['status'])
                # Mark all items as delivered
                order.items.update(item_status='delivered')
            else:
                order.status = 'ready_for_delivery'
                order.save(update_fields=['status'])
            messages.success(request, 'Delivery record created.')
    return redirect('order_detail', pk=order_pk)


@login_required
def delivery_confirm(request, order_pk):
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    delivery = get_object_or_404(Delivery, order=order)
    delivery.is_delivered = True
    delivery.delivery_date = timezone.now().date()
    delivery.save()
    order.status = 'delivered'
    order.save(update_fields=['status'])
    order.items.update(item_status='delivered')
    messages.success(request, f'Order #{order.pk} marked as delivered.')
    return redirect('order_detail', pk=order_pk)


@login_required
def report_view(request):
    today = timezone.now().date()

    # Orders by status
    order_stats = CustomerOrder.objects.values('status').annotate(count=Count('id'))

    # Overdue orders
    overdue_orders = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).select_related('customer').order_by('due_date')

    # Top customers by orders
    top_customers = Customer.objects.annotate(
        order_count=Count('orders')
    ).order_by('-order_count')[:10]

    # Revenue summary
    revenue = CustomerOrder.objects.exclude(
        status='cancelled'
    ).aggregate(
        total_invoiced=Sum('final_amount'),
        total_paid=Sum('payments__amount')
    )

    # Tickets by stage
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

    # Pending damage incidents
    unresolved_incidents = DamageIncident.objects.filter(
        is_resolved=False
    ).select_related('order_item__order__customer', 'reported_by')

    context = {
        'order_status_rows': order_status_rows,
        'stage_bar_max': stage_bar_max,
        'overdue_orders': overdue_orders,
        'top_customers': top_customers,
        'revenue': revenue,
        'tickets_by_stage': tickets_by_stage,
        'unresolved_incidents': unresolved_incidents,
        'today': today,
    }
    return render(request, 'shop/report.html', context)


@login_required
def employee_list(request):
    employees = Employee.objects.filter(is_active=True).annotate(
        active_tasks=Count('task_assignments', filter=Q(task_assignments__assignment_status='current'))
    )
    return render(request, 'shop/employee_list.html', {'employees': employees})


def portal_home(request):
    """Public landing page for the sewing shop."""
    return render(request, 'portal/home.html')


def portal_register(request):
    """Customer self-registration."""
    if (
        request.user.is_authenticated
        and not request.user.is_staff
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
            password=password1, first_name=first_name, last_name=last_name
        )
        customer = Customer.objects.create(
            user=user, first_name=first_name, last_name=last_name,
            email=email, phone=phone, address=address
        )
        login(request, user)
        messages.success(request, f'Welcome, {first_name}! Your account has been created.')
        return redirect('portal_dashboard')
    return render(request, 'portal/register.html')


def portal_login(request):
    """Customer login."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        if Customer.objects.filter(user=request.user).exists():
            return redirect('portal_dashboard')
        return render(request, 'portal/login.html', {
            'error': 'This account is not linked to a customer profile. Please register a customer account or use the staff login.',
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
        else:
            return render(request, 'portal/login.html', {'error': 'Invalid email or password.', 'email': email})
    return render(request, 'portal/login.html')


def portal_logout(request):
    logout(request)
    return redirect('portal_home')


def portal_dashboard(request):
    """Customer's personal dashboard."""
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
    # region agent log
    debug_run_id = request.GET.get('debug_run_id', 'initial')
    active_preview = []
    for order in active[:5]:
        active_preview.append({
            'orderId': order.pk,
            'finalAmount': str(order.final_amount),
            'itemCount': order.items.count(),
            'status': order.status,
        })
    _append_debug_log(
        run_id=debug_run_id,
        hypothesis_id='H4_customer_dashboard_without_price_field',
        location='shop/views.py:portal_dashboard',
        message='Portal dashboard pricing preview',
        data={
            'customerId': customer.pk,
            'activeCount': active.count(),
            'completedCount': completed.count(),
            'activePreview': active_preview,
        },
    )
    # endregion
    return render(request, 'portal/dashboard.html', {
        'customer': customer,
        'active_orders': active,
        'completed_orders': completed,
        'upcoming_orders': upcoming,
    })


def portal_order_detail(request, pk):
    """Customer views their order detail and production status."""
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('order_detail', pk=pk)
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    order = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    items = order.items.prefetch_related('tickets__current_stage', 'tickets__status_history__stage').all()
    try:
        delivery = order.delivery
    except Exception:
        delivery = None
    # region agent log
    debug_run_id = request.GET.get('debug_run_id', 'initial')
    _append_debug_log(
        run_id=debug_run_id,
        hypothesis_id='H2_customer_price_hidden_by_template_branch',
        location='shop/views.py:portal_order_detail',
        message='Portal order detail pricing context',
        data={
            'orderId': order.pk,
            'finalAmount': str(order.final_amount),
            'isTruthyFinalAmount': bool(order.final_amount),
            'paymentStatus': order.payment_status,
            'deliveryExists': delivery is not None,
            'itemCount': items.count(),
        },
    )
    # endregion
    return render(request, 'portal/order_detail.html', {
        'order': order, 'items': items, 'delivery': delivery
    })


def portal_book(request):
    """Customer submits a booking/inquiry request."""
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('dashboard')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')

    GARMENT_TYPES = [
        'Dress', 'Blouse', 'Skirt', 'Trousers', 'Suit Jacket',
        'Wedding Gown', 'Shirt', 'Coat', 'Alteration', 'Other'
    ]

    if request.method == 'POST':
        due_date = request.POST.get('due_date')
        notes = request.POST.get('notes', '').strip()
        priority = request.POST.get('priority', 'normal')
        garment_type = request.POST.get('garment_type', '').strip()
        fabric = request.POST.get('fabric', '').strip()
        color = request.POST.get('color', '').strip()
        special_instructions = request.POST.get('special_instructions', '').strip()
        quantity = int(request.POST.get('quantity', 1))

        if not due_date or not garment_type:
            return render(request, 'portal/book.html', {
                'error': 'Please fill in all required fields.',
                'data': request.POST,
                'garment_types': GARMENT_TYPES,
            })

        order = CustomerOrder.objects.create(
            customer=customer,
            due_date=due_date,
            priority=priority,
            status='received',
            payment_status='unpaid',
        )
        OrderItem.objects.create(
            order=order,
            garment_type=garment_type,
            fabric=fabric,
            color=color,
            quantity=quantity,
            special_instructions=special_instructions,
        )
        order.recalculate_amounts()
        messages.success(
            request,
            f'Your booking #{order.pk} has been submitted and priced automatically.',
        )
        return redirect('portal_order_detail', pk=order.pk)

    return render(request, 'portal/book.html', {'garment_types': GARMENT_TYPES})


def portal_profile(request):
    """Customer edits their profile."""
    if not request.user.is_authenticated:
        return redirect('portal_login')
    try:
        customer = Customer.objects.get(user=request.user)
    except Customer.DoesNotExist:
        return redirect('portal_login')
    if request.method == 'POST':
        customer.phone = request.POST.get('phone', '').strip()
        customer.address = request.POST.get('address', '').strip()
        customer.notes = request.POST.get('notes', '').strip()
        customer.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('portal_profile')
    return render(request, 'portal/profile.html', {'customer': customer})


def _get_employee(request):
    """Helper: get Employee linked to logged-in user, or None."""
    try:
        return Employee.objects.get(user=request.user)
    except Employee.DoesNotExist:
        return None


def _authenticate_by_email_or_username(request, email, password):
    """
    Django's authenticate() uses User.USERNAME_FIELD (username).
    Try the value as username first, then match a User by email (case-insensitive).
    """
    user = authenticate(request, username=email, password=password)
    if user is not None:
        return user
    if not email or not password:
        return None
    candidates = User.objects.filter(email__iexact=email)
    for u in candidates:
        candidate = authenticate(request, username=u.username, password=password)
        if candidate is not None:
            return candidate
    return None


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
            emp = None
            try:
                emp = Employee.objects.get(user=user)
            except Employee.DoesNotExist:
                pass
            if emp:
                login(request, user)
                return redirect('emp_dashboard')
            elif user.is_staff:
                login(request, user)
                return redirect('dashboard')
            else:
                return render(request, 'employee/login.html', {
                    'error': 'No employee account linked to this user. Contact your manager.',
                    'email': email
                })
        return render(request, 'employee/login.html', {
            'error': 'Invalid email or password.',
            'email': email
        })
    return render(request, 'employee/login.html')


def emp_logout(request):
    logout(request)
    return redirect('emp_login')


def emp_required(view_func):
    """Decorator: must be logged in AND have an Employee record."""
    from functools import wraps
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


@emp_required
def emp_dashboard(request, employee):
    today = timezone.now().date()
    # My open tickets
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
        ticket__in=my_assignments,
        changed_at__date=today,
        stage__stage_name__icontains='quality'
    ).count()
    shop_overdue = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=['delivered', 'cancelled']).count()

    pipeline = ProductionStage.objects.annotate(
        ticket_count=Count('active_tickets', filter=Q(
            active_tickets__status__in=['open', 'assigned', 'in_progress']
        ))
    ).order_by('stage_order')

    return render(request, 'employee/dashboard.html', {
        'employee': employee,
        'my_tickets': my_tickets_qs,
        'my_open': my_open,
        'my_urgent': my_urgent,
        'my_done_today': my_done_today,
        'shop_overdue': shop_overdue,
        'pipeline': pipeline,
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
        'employee': employee, 'tickets': tickets
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
        'employee': employee, 'tickets': tickets
    })


@emp_required
def emp_ticket_detail(request, pk, employee):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    history = ticket.status_history.select_related('stage', 'changed_by').order_by('changed_at')
    stages = ProductionStage.objects.order_by('stage_order')
    incidents = ticket.damage_incidents.all()
    return render(request, 'employee/ticket_detail.html', {
        'employee': employee,
        'ticket': ticket,
        'history': history,
        'stages': stages,
        'incidents': incidents,
    })


@emp_required
def emp_update_stage(request, pk, employee):
    if request.method != 'POST':
        return redirect('emp_ticket_detail', pk=pk)
    ticket = get_object_or_404(WorkTicket, pk=pk)
    stage_id = request.POST.get('stage')
    comment = request.POST.get('comment', '').strip()
    try:
        stage = ProductionStage.objects.get(pk=stage_id)
        ticket.current_stage = stage
        if ticket.status in ['open', 'assigned']:
            ticket.status = 'in_progress'
        ticket.save()
        TicketStatusHistory.objects.create(
            ticket=ticket,
            stage=stage,
            changed_by=employee,
            comment=comment or f"Stage updated by {employee.full_name}"
        )
        messages.success(request, f'Stage updated to "{stage.stage_name}".')
    except ProductionStage.DoesNotExist:
        messages.error(request, 'Invalid stage selected.')
    return redirect('emp_ticket_detail', pk=pk)


@emp_required
def emp_complete_ticket(request, pk, employee):
    if request.method != 'POST':
        return redirect('emp_ticket_detail', pk=pk)
    ticket = get_object_or_404(WorkTicket, pk=pk)
    comment = request.POST.get('comment', '').strip()
    ticket.status = 'completed'
    ticket.save()
    last_stage = ProductionStage.objects.order_by('-stage_order').first()
    if last_stage:
        TicketStatusHistory.objects.create(
            ticket=ticket,
            stage=last_stage,
            changed_by=employee,
            comment=comment or f"Completed by {employee.full_name}"
        )
    item = ticket.order_item
    all_done = not item.tickets.exclude(status='completed').exists()
    if all_done:
        item.item_status = 'completed'
        item.save()
        order = item.order
        if not order.items.exclude(item_status='completed').exists():
            order.status = 'ready_for_delivery'
            order.save(update_fields=['status'])
    messages.success(request, f'Ticket {ticket.ticket_code} marked as completed!')
    return redirect('emp_my_tickets')


@emp_required
def emp_orders(request, employee):
    orders = CustomerOrder.objects.exclude(
        status__in=['delivered', 'cancelled']
    ).select_related('customer').order_by('due_date')
    return render(request, 'employee/orders.html', {
        'employee': employee, 'orders': orders
    })


@emp_required
def emp_profile(request, employee):
    return render(request, 'employee/profile.html', {'employee': employee})
