"""View layer for the sewing shop management system.

This module groups the views by audience. The first group covers the staff
back office that is reachable at ``/dashboard/``, ``/customers/`` and so on.
The second group is the customer self service portal mounted at
``/portal/``. The third group is the employee portal mounted at
``/staff/``. Helper functions and named status constants used across these
groups live at the top of the module so that the views read like business
descriptions instead of strings of database lookups.
"""

from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    CustomerForm,
    CustomerOrderForm,
    DamageIncidentForm,
    DeliveryForm,
    MaterialForm,
    MeasurementForm,
    OrderItemForm,
    OrderItemMaterialForm,
    PaymentForm,
    TaskAssignmentForm,
    TicketStatusUpdateForm,
    WorkTicketForm,
)
from .models import (
    Customer,
    CustomerOrder,
    DamageIncident,
    Delivery,
    Employee,
    Material,
    Measurement,
    OrderItem,
    OrderItemMaterial,
    Payment,
    ProductionStage,
    TaskAssignment,
    TicketStatusHistory,
    WorkTicket,
)


# ---------------------------------------------------------------------------
# Named status constants.
#
# The codebase uses string enumerations for order, order item and ticket
# statuses. Having dedicated constants here avoids string typos, prevents
# magic values from spreading across the views, and lets the reader scan the
# state machine at a glance.
# ---------------------------------------------------------------------------

ORDER_STATUS_DRAFT = 'draft'
ORDER_STATUS_RECEIVED = 'received'
ORDER_STATUS_IN_PRODUCTION = 'in_production'
ORDER_STATUS_COMPLETED = 'completed'
ORDER_STATUS_READY_FOR_DELIVERY = 'ready_for_delivery'
ORDER_STATUS_DELIVERED = 'delivered'
ORDER_STATUS_CANCELLED = 'cancelled'

ACTIVE_ORDER_STATUSES = frozenset({
    ORDER_STATUS_RECEIVED,
    ORDER_STATUS_IN_PRODUCTION,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_READY_FOR_DELIVERY,
    ORDER_STATUS_DELIVERED,
})

CLOSED_ORDER_STATUSES = frozenset({
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_CANCELLED,
})

ITEM_STATUS_PENDING = 'pending'
ITEM_STATUS_IN_PROGRESS = 'in_progress'
ITEM_STATUS_COMPLETED = 'completed'
ITEM_STATUS_DAMAGED = 'damaged'
ITEM_STATUS_DELIVERED = 'delivered'

CLOSED_ITEM_STATUSES = frozenset({
    ITEM_STATUS_COMPLETED,
    ITEM_STATUS_DELIVERED,
    'cancelled',
})

TICKET_STATUS_OPEN = 'open'
TICKET_STATUS_ASSIGNED = 'assigned'
TICKET_STATUS_IN_PROGRESS = 'in_progress'
TICKET_STATUS_BLOCKED = 'blocked'
TICKET_STATUS_COMPLETED = 'completed'
TICKET_STATUS_CANCELLED = 'cancelled'

ACTIVE_TICKET_STATUSES = frozenset({
    TICKET_STATUS_OPEN,
    TICKET_STATUS_ASSIGNED,
    TICKET_STATUS_IN_PROGRESS,
})

CLOSED_TICKET_STATUSES = frozenset({
    TICKET_STATUS_COMPLETED,
    TICKET_STATUS_CANCELLED,
})

ASSIGNMENT_STATUS_CURRENT = 'current'
ASSIGNMENT_STATUS_REASSIGNED = 'reassigned'

PAYMENT_STATUS_UNPAID = 'unpaid'
PAYMENT_STATUS_PARTIALLY_PAID = 'partially_paid'
PAYMENT_STATUS_PAID = 'paid'

DUE_SOON_WINDOW_DAYS = 3
DASHBOARD_RECENT_ORDERS_LIMIT = 8
DASHBOARD_URGENT_TICKETS_LIMIT = 6
EMPLOYEE_DASHBOARD_TICKETS_LIMIT = 10
TOP_CUSTOMERS_LIMIT = 10
MIN_PASSWORD_LENGTH = 8
DEFAULT_PORTAL_QUANTITY = 1


# ---------------------------------------------------------------------------
# Helper functions used by multiple views.
# ---------------------------------------------------------------------------

def _customer_for_user(user):
    """Return the ``Customer`` linked to ``user`` or ``None`` when missing.

    Used by every customer portal view so that lookups are consistent and the
    redirect to the login page happens in exactly one place upstream.
    """
    try:
        return Customer.objects.get(user=user)
    except Customer.DoesNotExist:
        return None


def _employee_for_user(user):
    """Return the ``Employee`` linked to ``user`` or ``None`` when missing."""
    try:
        return Employee.objects.get(user=user)
    except Employee.DoesNotExist:
        return None


def _unresolved_damage_for_order(order):
    """Return the queryset of unresolved damage incidents on ``order``.

    Implements the read side of business rule ten: a delivery cannot be
    scheduled while any damage incident on the order is still open.
    """
    return DamageIncident.objects.filter(
        order_item__order=order,
        is_resolved=False,
    )


def _refresh_payment_status(order):
    """Update ``order.payment_status`` from the sum of its payments.

    The recalculation runs as a single query and saves only the affected
    field so concurrent edits to other fields are not lost.
    """
    total_paid = order.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    if total_paid >= order.final_amount and order.final_amount > 0:
        order.payment_status = PAYMENT_STATUS_PAID
    elif total_paid > 0:
        order.payment_status = PAYMENT_STATUS_PARTIALLY_PAID
    else:
        order.payment_status = PAYMENT_STATUS_UNPAID
    order.save(update_fields=['payment_status'])


def _propagate_item_completion(order_item):
    """Promote item and order status when production work finishes.

    The function checks whether every ticket of ``order_item`` reached a
    closed state. If so, the item itself becomes completed. It then checks
    whether every item of the parent order is closed; if all are, the order
    is set to ``ready_for_delivery`` so it surfaces in the delivery queue.
    """
    has_open_tickets = order_item.tickets.exclude(
        status__in=CLOSED_TICKET_STATUSES
    ).exists()
    if has_open_tickets:
        return

    order_item.item_status = ITEM_STATUS_COMPLETED
    order_item.save(update_fields=['item_status'])

    parent_order = order_item.order
    has_open_items = parent_order.items.exclude(
        item_status__in=CLOSED_ITEM_STATUSES
    ).exists()
    if has_open_items or parent_order.status in CLOSED_ORDER_STATUSES:
        return

    parent_order.status = ORDER_STATUS_READY_FOR_DELIVERY
    parent_order.save(update_fields=['status'])


def _close_current_assignment(ticket):
    """Mark the live assignment of ``ticket`` as reassigned.

    Used before creating a new ``TaskAssignment`` so that the invariant
    "at most one current assignment per ticket" holds at all times.
    """
    ticket.assignments.filter(
        assignment_status=ASSIGNMENT_STATUS_CURRENT
    ).update(
        assignment_status=ASSIGNMENT_STATUS_REASSIGNED,
        unassigned_at=timezone.now(),
    )


def _normalise_email(raw_email):
    """Return a stripped lower case copy of ``raw_email``.

    Customer and employee log in flows look users up by email, and this
    function is the single place where that normalisation happens.
    """
    return (raw_email or '').strip().lower()


# ---------------------------------------------------------------------------
# Staff dashboard, customers, orders, items, measurements.
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    """Render the shop wide dashboard with order, ticket and pipeline stats."""
    today = timezone.now().date()
    due_soon_end = today + timedelta(days=DUE_SOON_WINDOW_DAYS)

    total_orders = CustomerOrder.objects.count()
    pending_orders = CustomerOrder.objects.filter(
        status__in=[ORDER_STATUS_DRAFT, ORDER_STATUS_RECEIVED]
    ).count()
    in_production = CustomerOrder.objects.filter(status=ORDER_STATUS_IN_PRODUCTION).count()
    completed_orders = CustomerOrder.objects.filter(status=ORDER_STATUS_COMPLETED).count()
    delivered_orders = CustomerOrder.objects.filter(status=ORDER_STATUS_DELIVERED).count()

    overdue_orders = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=CLOSED_ORDER_STATUSES).count()

    open_tickets = WorkTicket.objects.filter(status__in=ACTIVE_TICKET_STATUSES).count()
    overdue_tickets = WorkTicket.objects.filter(
        deadline__lt=today
    ).exclude(status__in=CLOSED_TICKET_STATUSES).count()
    blocked_tickets = WorkTicket.objects.filter(status=TICKET_STATUS_BLOCKED).count()

    recent_orders = (
        CustomerOrder.objects
        .select_related('customer')
        .order_by('-created_at')[:DASHBOARD_RECENT_ORDERS_LIMIT]
    )

    urgent_tickets = (
        WorkTicket.objects
        .filter(priority__in=['high', 'urgent'])
        .exclude(status__in=CLOSED_TICKET_STATUSES)
        .select_related('order_item__order__customer', 'current_stage')
        .order_by('-priority', 'deadline')[:DASHBOARD_URGENT_TICKETS_LIMIT]
    )

    damage_count = DamageIncident.objects.filter(is_resolved=False).count()

    due_soon = CustomerOrder.objects.filter(
        due_date__range=[today, due_soon_end]
    ).exclude(status__in=CLOSED_ORDER_STATUSES).select_related('customer').count()

    stages = ProductionStage.objects.annotate(
        ticket_count=Count(
            'active_tickets',
            filter=Q(active_tickets__status__in=ACTIVE_TICKET_STATUSES),
        )
    ).order_by('stage_order')

    context = {
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'in_production': in_production,
        'completed_orders': completed_orders,
        'delivered_orders': delivered_orders,
        'overdue_orders': overdue_orders,
        'open_tickets': open_tickets,
        'overdue_tickets': overdue_tickets,
        'blocked_tickets': blocked_tickets,
        'damage_count': damage_count,
        'due_soon': due_soon,
        'recent_orders': recent_orders,
        'urgent_tickets': urgent_tickets,
        'stages': stages,
        'today': today,
    }
    return render(request, 'shop/dashboard.html', context)


@login_required
def customer_list(request):
    """List customers with an optional case insensitive search filter."""
    search_term = request.GET.get('q', '').strip()
    customers = Customer.objects.annotate(order_count=Count('orders'))
    if search_term:
        customers = customers.filter(
            Q(first_name__icontains=search_term)
            | Q(last_name__icontains=search_term)
            | Q(phone__icontains=search_term)
            | Q(email__icontains=search_term)
        )
    return render(
        request,
        'shop/customer_list.html',
        {'customers': customers, 'q': search_term},
    )


@login_required
def customer_create(request):
    """Register a new customer record from the staff form."""
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(
                request,
                f'Customer {customer.full_name} registered successfully.',
            )
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm()
    return render(
        request,
        'shop/customer_form.html',
        {'form': form, 'title': 'Register a new customer'},
    )


@login_required
def customer_detail(request, pk):
    """Show the customer file together with the list of past orders."""
    customer = get_object_or_404(Customer, pk=pk)
    orders = (
        customer.orders
        .select_related()
        .prefetch_related('items')
        .order_by('-created_at')
    )
    return render(
        request,
        'shop/customer_detail.html',
        {'customer': customer, 'orders': orders},
    )


@login_required
def customer_edit(request, pk):
    """Edit the contact details and notes of an existing customer."""
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer updated successfully.')
            return redirect('customer_detail', pk=customer.pk)
    else:
        form = CustomerForm(instance=customer)
    return render(
        request,
        'shop/customer_form.html',
        {
            'form': form,
            'customer': customer,
            'title': f'Edit {customer.full_name}',
        },
    )


@login_required
def order_list(request):
    """List orders with optional filters by status, priority and search term."""
    status_filter = request.GET.get('status', '').strip()
    priority_filter = request.GET.get('priority', '').strip()
    search_term = request.GET.get('q', '').strip()
    today = timezone.now().date()

    orders = CustomerOrder.objects.select_related('customer').prefetch_related('items')
    if status_filter:
        orders = orders.filter(status=status_filter)
    if priority_filter:
        orders = orders.filter(priority=priority_filter)
    if search_term:
        orders = orders.filter(
            Q(customer__first_name__icontains=search_term)
            | Q(customer__last_name__icontains=search_term)
        )

    overdue_ids = [order.pk for order in orders if order.is_overdue]

    context = {
        'orders': orders.order_by('-created_at'),
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'q': search_term,
        'overdue_ids': overdue_ids,
        'status_choices': CustomerOrder.STATUS_CHOICES,
        'priority_choices': CustomerOrder.PRIORITY_CHOICES,
        'today': today,
    }
    return render(request, 'shop/order_list.html', context)


@login_required
def order_create(request):
    """Create a new order, optionally pre selecting a customer from the URL."""
    initial_data = {}
    customer_id = request.GET.get('customer')
    if customer_id:
        initial_data['customer'] = customer_id

    if request.method == 'POST':
        form = CustomerOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            order.status = ORDER_STATUS_RECEIVED
            order.save()
            messages.success(
                request,
                f'Order #{order.pk} created. The next step is to add garment items.',
            )
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(initial=initial_data)
    return render(
        request,
        'shop/order_form.html',
        {'form': form, 'title': 'Create a new order'},
    )


@login_required
def order_detail(request, pk):
    """Show the order with its items, materials, payments and delivery."""
    order = get_object_or_404(CustomerOrder, pk=pk)
    items = order.items.prefetch_related(
        'measurements',
        'tickets',
        'damage_incidents',
        'materials_used__material',
    )
    payments = order.payments.all()
    delivery = getattr(order, 'delivery', None)
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    context = {
        'order': order,
        'items': items,
        'payments': payments,
        'delivery': delivery,
        'total_paid': total_paid,
        'balance': order.final_amount - total_paid,
        'today': timezone.now().date(),
    }
    return render(request, 'shop/order_detail.html', context)


@login_required
def order_edit(request, pk):
    """Edit the metadata of an existing order."""
    order = get_object_or_404(CustomerOrder, pk=pk)
    if request.method == 'POST':
        form = CustomerOrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, f'Order #{order.pk} updated.')
            return redirect('order_detail', pk=order.pk)
    else:
        form = CustomerOrderForm(instance=order)
    return render(
        request,
        'shop/order_form.html',
        {
            'form': form,
            'order': order,
            'title': f'Edit order #{order.pk}',
        },
    )


@login_required
def order_status_update(request, pk):
    """Change the status of an order, enforcing business rule number two.

    Business rule two requires an order to contain at least one item before
    it may leave the draft state. The function rejects the transition with a
    user facing message instead of silently failing.
    """
    order = get_object_or_404(CustomerOrder, pk=pk)
    new_status = request.POST.get('status', '').strip()
    valid_statuses = dict(CustomerOrder.STATUS_CHOICES)
    if not new_status or new_status not in valid_statuses:
        return redirect('order_detail', pk=order.pk)

    if new_status in ACTIVE_ORDER_STATUSES and not order.items.exists():
        messages.error(
            request,
            'Add at least one garment to the order before moving it out of draft.',
        )
        return redirect('order_detail', pk=order.pk)

    order.status = new_status
    order.save(update_fields=['status'])
    messages.success(
        request,
        f'Order status updated to {order.get_status_display()}.',
    )
    return redirect('order_detail', pk=order.pk)


@login_required
def orderitem_create(request, order_pk):
    """Add a garment item to an order and recompute the order total."""
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method == 'POST':
        form = OrderItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.order = order
            item.save()
            order.recalculate_amounts()
            messages.success(
                request,
                f'Garment "{item.garment_type}" added to the order.',
            )
            return redirect('order_detail', pk=order.pk)
    else:
        form = OrderItemForm()
    return render(
        request,
        'shop/orderitem_form.html',
        {
            'form': form,
            'order': order,
            'title': 'Add a garment to the order',
        },
    )


@login_required
def orderitem_edit(request, pk):
    """Edit an existing order item and recompute the parent order total."""
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
    return render(
        request,
        'shop/orderitem_form.html',
        {
            'form': form,
            'order': item.order,
            'item': item,
            'title': f'Edit {item.garment_type}',
        },
    )


@login_required
def measurement_add(request, item_pk):
    """Record a measurement for the given order item."""
    item = get_object_or_404(OrderItem, pk=item_pk)
    if request.method == 'POST':
        form = MeasurementForm(request.POST)
        if form.is_valid():
            measurement = form.save(commit=False)
            measurement.order_item = item
            measurement.save()
            messages.success(request, 'Measurement recorded.')
            return redirect('order_detail', pk=item.order.pk)
    else:
        form = MeasurementForm()
    return render(request, 'shop/measurement_form.html', {'form': form, 'item': item})


# ---------------------------------------------------------------------------
# Work tickets and assignments.
# ---------------------------------------------------------------------------

@login_required
def ticket_list(request):
    """List work tickets with filters by status, priority, stage and search."""
    status_filter = request.GET.get('status', '').strip()
    priority_filter = request.GET.get('priority', '').strip()
    stage_filter = request.GET.get('stage', '').strip()
    search_term = request.GET.get('q', '').strip()
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
    if search_term:
        tickets = tickets.filter(
            Q(ticket_code__icontains=search_term)
            | Q(order_item__garment_type__icontains=search_term)
            | Q(order_item__order__customer__first_name__icontains=search_term)
            | Q(order_item__order__customer__last_name__icontains=search_term)
        )

    context = {
        'tickets': tickets.order_by('-created_at'),
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'stage_filter': stage_filter,
        'q': search_term,
        'stages': ProductionStage.objects.all(),
        'status_choices': WorkTicket.TICKET_STATUS_CHOICES,
        'priority_choices': WorkTicket.PRIORITY_CHOICES,
        'today': today,
    }
    return render(request, 'shop/ticket_list.html', context)


@login_required
def ticket_create(request, item_pk=None):
    """Create a work ticket, optionally pre attached to an order item.

    The new ticket is positioned at the first production stage and a status
    history row is created for that stage so the audit trail starts at
    creation rather than at the first manual update.
    """
    initial_data = {}
    order_item = None
    if item_pk:
        order_item = get_object_or_404(OrderItem, pk=item_pk)
        initial_data['order_item'] = order_item

    first_stage = ProductionStage.objects.order_by('stage_order').first()
    if first_stage:
        initial_data['current_stage'] = first_stage

    if request.method == 'POST':
        form = WorkTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save()
            TicketStatusHistory.objects.create(
                ticket=ticket,
                stage=ticket.current_stage,
                comment='Ticket created.',
            )
            ticket.order_item.item_status = ITEM_STATUS_IN_PROGRESS
            ticket.order_item.save(update_fields=['item_status'])

            parent_order = ticket.order_item.order
            if parent_order.status == ORDER_STATUS_RECEIVED:
                parent_order.status = ORDER_STATUS_IN_PRODUCTION
                parent_order.save(update_fields=['status'])

            messages.success(request, f'Work ticket {ticket.ticket_code} created.')
            return redirect('ticket_detail', pk=ticket.pk)
    else:
        form = WorkTicketForm(initial=initial_data)
    return render(
        request,
        'shop/ticket_form.html',
        {
            'form': form,
            'order_item': order_item,
            'title': 'Create a work ticket',
        },
    )


@login_required
def ticket_detail(request, pk):
    """Show a ticket with its history, assignments, incidents and forms."""
    ticket = get_object_or_404(WorkTicket, pk=pk)
    history = (
        ticket.status_history
        .select_related('stage', 'changed_by')
        .order_by('-changed_at')
    )
    assignments = ticket.assignments.select_related('employee').order_by('-assigned_at')
    incidents = ticket.damage_incidents.select_related('reported_by')

    context = {
        'ticket': ticket,
        'history': history,
        'assignments': assignments,
        'incidents': incidents,
        'update_form': TicketStatusUpdateForm(),
        'assign_form': TaskAssignmentForm(),
        'today': timezone.now().date(),
    }
    return render(request, 'shop/ticket_detail.html', context)


@login_required
def ticket_update_stage(request, pk):
    """Move a ticket to a new stage and append an audit row.

    When the new status closes the ticket, the helper
    ``_propagate_item_completion`` checks whether the parent item and order
    can also be closed, keeping the state machines in sync.
    """
    ticket = get_object_or_404(WorkTicket, pk=pk)
    if request.method != 'POST':
        return redirect('ticket_detail', pk=ticket.pk)

    form = TicketStatusUpdateForm(request.POST)
    if not form.is_valid():
        return redirect('ticket_detail', pk=ticket.pk)

    stage = form.cleaned_data['stage']
    new_status = form.cleaned_data['status']
    changed_by = form.cleaned_data.get('changed_by')
    comment = form.cleaned_data.get('comment', '')

    ticket.current_stage = stage
    ticket.status = new_status
    ticket.save(update_fields=['current_stage', 'status', 'updated_at'])

    TicketStatusHistory.objects.create(
        ticket=ticket,
        stage=stage,
        changed_by=changed_by,
        comment=comment,
    )

    if new_status == TICKET_STATUS_COMPLETED:
        _propagate_item_completion(ticket.order_item)

    messages.success(request, f'Ticket moved to stage: {stage.stage_name}.')
    return redirect('ticket_detail', pk=ticket.pk)


@login_required
def ticket_assign(request, pk):
    """Assign an employee to a ticket and close any existing assignment."""
    ticket = get_object_or_404(WorkTicket, pk=pk)
    if request.method != 'POST':
        return redirect('ticket_detail', pk=pk)

    form = TaskAssignmentForm(request.POST)
    if not form.is_valid():
        return redirect('ticket_detail', pk=pk)

    _close_current_assignment(ticket)
    assignment = form.save(commit=False)
    assignment.ticket = ticket
    assignment.assignment_status = ASSIGNMENT_STATUS_CURRENT
    assignment.save()

    ticket.status = TICKET_STATUS_ASSIGNED
    ticket.save(update_fields=['status'])

    messages.success(
        request,
        f'Ticket assigned to {assignment.employee.full_name}.',
    )
    return redirect('ticket_detail', pk=pk)


# ---------------------------------------------------------------------------
# Damage incidents.
# ---------------------------------------------------------------------------

@login_required
def damage_incident_create(request, ticket_pk):
    """Record a damage incident and block the related ticket."""
    ticket = get_object_or_404(WorkTicket, pk=ticket_pk)
    if request.method != 'POST':
        return redirect('ticket_detail', pk=ticket_pk)

    form = DamageIncidentForm(request.POST)
    if not form.is_valid():
        return redirect('ticket_detail', pk=ticket_pk)

    incident = form.save(commit=False)
    incident.ticket = ticket
    incident.order_item = ticket.order_item
    incident.save()

    ticket.order_item.item_status = ITEM_STATUS_DAMAGED
    ticket.order_item.save(update_fields=['item_status'])

    ticket.status = TICKET_STATUS_BLOCKED
    ticket.save(update_fields=['status'])

    messages.warning(
        request,
        'Damage incident recorded. The ticket is now blocked pending resolution.',
    )
    return redirect('ticket_detail', pk=ticket_pk)


@login_required
def damage_incident_resolve(request, pk):
    """Resolve a damage incident and unblock the ticket when possible."""
    incident = get_object_or_404(DamageIncident, pk=pk)
    if request.method != 'POST':
        return redirect('ticket_detail', pk=incident.ticket.pk)

    incident.is_resolved = True
    incident.resolution_action = request.POST.get(
        'resolution_action', incident.resolution_action
    )
    incident.resolution_notes = request.POST.get('resolution_notes', '')
    incident.save()

    ticket = incident.ticket
    has_open_incidents = ticket.damage_incidents.filter(is_resolved=False).exists()
    if not has_open_incidents:
        ticket.status = TICKET_STATUS_IN_PROGRESS
        ticket.save(update_fields=['status'])

    messages.success(request, 'Incident resolved.')
    return redirect('ticket_detail', pk=ticket.pk)


# ---------------------------------------------------------------------------
# Payments and delivery.
# ---------------------------------------------------------------------------

@login_required
def payment_add(request, order_pk):
    """Record a payment against an order and refresh the payment status."""
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method != 'POST':
        return redirect('order_detail', pk=order_pk)

    form = PaymentForm(request.POST)
    if not form.is_valid():
        return redirect('order_detail', pk=order_pk)

    payment = form.save(commit=False)
    payment.order = order
    payment.recorded_by = request.user
    payment.save()
    _refresh_payment_status(order)

    messages.success(request, f'Payment of ${payment.amount} recorded.')
    return redirect('order_detail', pk=order_pk)


@login_required
def delivery_create(request, order_pk):
    """Schedule a delivery, blocking the action when damage is unresolved.

    Implements business rule ten on the create side: a delivery cannot be
    created while at least one damage incident on the order is still open.
    """
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    if request.method != 'POST':
        return redirect('order_detail', pk=order_pk)

    blocking_incidents = _unresolved_damage_for_order(order)
    if blocking_incidents.exists():
        messages.error(
            request,
            'A delivery cannot be scheduled because '
            f'{blocking_incidents.count()} damage incident(s) remain unresolved. '
            'Resolve those incidents first.',
        )
        return redirect('order_detail', pk=order_pk)

    form = DeliveryForm(request.POST)
    if not form.is_valid():
        return redirect('order_detail', pk=order_pk)

    delivery = form.save(commit=False)
    delivery.order = order
    delivery.save()

    if delivery.is_delivered:
        order.status = ORDER_STATUS_DELIVERED
        order.save(update_fields=['status'])
        order.items.update(item_status=ITEM_STATUS_DELIVERED)
    else:
        order.status = ORDER_STATUS_READY_FOR_DELIVERY
        order.save(update_fields=['status'])

    messages.success(request, 'Delivery record created.')
    return redirect('order_detail', pk=order_pk)


@login_required
def delivery_confirm(request, order_pk):
    """Confirm an existing delivery once damage incidents are resolved.

    Implements business rule ten on the confirm side. The check is performed
    even when the delivery already exists because incidents can be added
    between scheduling and pickup.
    """
    order = get_object_or_404(CustomerOrder, pk=order_pk)
    delivery = get_object_or_404(Delivery, order=order)

    blocking_incidents = _unresolved_damage_for_order(order)
    if blocking_incidents.exists():
        messages.error(
            request,
            'The delivery cannot be confirmed because '
            f'{blocking_incidents.count()} damage incident(s) remain unresolved. '
            'Resolve those incidents first.',
        )
        return redirect('order_detail', pk=order_pk)

    delivery.is_delivered = True
    delivery.delivery_date = timezone.now().date()
    delivery.save()

    order.status = ORDER_STATUS_DELIVERED
    order.save(update_fields=['status'])
    order.items.update(item_status=ITEM_STATUS_DELIVERED)

    messages.success(request, f'Order #{order.pk} marked as delivered.')
    return redirect('order_detail', pk=order_pk)


# ---------------------------------------------------------------------------
# Reports and employees.
# ---------------------------------------------------------------------------

@login_required
def report_view(request):
    """Render the analytics page with order, ticket and revenue snapshots."""
    today = timezone.now().date()

    order_stats = CustomerOrder.objects.values('status').annotate(count=Count('id'))

    overdue_orders = (
        CustomerOrder.objects
        .filter(due_date__lt=today)
        .exclude(status__in=CLOSED_ORDER_STATUSES)
        .select_related('customer')
        .order_by('due_date')
    )

    top_customers = (
        Customer.objects
        .annotate(order_count=Count('orders'))
        .order_by('-order_count')[:TOP_CUSTOMERS_LIMIT]
    )

    revenue = CustomerOrder.objects.exclude(
        status=ORDER_STATUS_CANCELLED
    ).aggregate(
        total_invoiced=Sum('final_amount'),
        total_paid=Sum('payments__amount'),
    )

    tickets_by_stage = ProductionStage.objects.annotate(
        ticket_count=Count(
            'active_tickets',
            filter=Q(active_tickets__status__in=ACTIVE_TICKET_STATUSES),
        )
    ).order_by('stage_order')

    unresolved_incidents = DamageIncident.objects.filter(
        is_resolved=False
    ).select_related('order_item__order__customer', 'reported_by')

    context = {
        'order_stats': {row['status']: row['count'] for row in order_stats},
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
    """List active employees together with their current task counts."""
    employees = Employee.objects.filter(is_active=True).annotate(
        active_tasks=Count(
            'task_assignments',
            filter=Q(task_assignments__assignment_status=ASSIGNMENT_STATUS_CURRENT),
        )
    )
    return render(request, 'shop/employee_list.html', {'employees': employees})


# ---------------------------------------------------------------------------
# Material catalog and per garment material usage.
# ---------------------------------------------------------------------------

@login_required
def material_list(request):
    """List the material catalog with optional search and category filter."""
    search_term = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    materials = Material.objects.annotate(usage_count=Count('usage_records'))
    if search_term:
        materials = materials.filter(
            Q(name__icontains=search_term)
            | Q(color__icontains=search_term)
            | Q(supplier__icontains=search_term)
        )
    if category:
        materials = materials.filter(category=category)
    return render(
        request,
        'shop/material_list.html',
        {
            'materials': materials,
            'q': search_term,
            'category': category,
            'category_choices': Material.CATEGORY_CHOICES,
        },
    )


@login_required
def material_create(request):
    """Add a material to the catalog."""
    if request.method == 'POST':
        form = MaterialForm(request.POST)
        if form.is_valid():
            material = form.save()
            messages.success(
                request,
                f'Material "{material.name}" added to the catalog.',
            )
            return redirect('material_list')
    else:
        form = MaterialForm()
    return render(
        request,
        'shop/material_form.html',
        {'form': form, 'title': 'Add a material to the catalog'},
    )


@login_required
def material_edit(request, pk):
    """Edit an existing material in the catalog."""
    material = get_object_or_404(Material, pk=pk)
    if request.method == 'POST':
        form = MaterialForm(request.POST, instance=material)
        if form.is_valid():
            form.save()
            messages.success(request, 'Material updated.')
            return redirect('material_list')
    else:
        form = MaterialForm(instance=material)
    return render(
        request,
        'shop/material_form.html',
        {'form': form, 'material': material, 'title': f'Edit {material.name}'},
    )


@login_required
def orderitem_material_add(request, item_pk):
    """Record that a given quantity of a material was used in a garment."""
    item = get_object_or_404(OrderItem, pk=item_pk)
    if request.method == 'POST':
        form = OrderItemMaterialForm(request.POST)
        if form.is_valid():
            usage = form.save(commit=False)
            usage.order_item = item
            if not form.cleaned_data.get('unit'):
                usage.unit = usage.material.default_unit
            usage.save()
            messages.success(
                request,
                f'Material "{usage.material.name}" recorded for this garment.',
            )
            return redirect('order_detail', pk=item.order.pk)
    else:
        form = OrderItemMaterialForm()
    return render(
        request,
        'shop/orderitem_material_form.html',
        {'form': form, 'item': item},
    )


@login_required
def orderitem_material_remove(request, pk):
    """Remove a material usage record from a garment."""
    usage = get_object_or_404(OrderItemMaterial, pk=pk)
    parent_order_pk = usage.order_item.order.pk
    if request.method == 'POST':
        usage.delete()
        messages.success(request, 'Material usage removed.')
    return redirect('order_detail', pk=parent_order_pk)


# ---------------------------------------------------------------------------
# Customer self service portal.
# ---------------------------------------------------------------------------

PORTAL_GARMENT_TYPES = [
    'Dress',
    'Blouse',
    'Skirt',
    'Trousers',
    'Suit Jacket',
    'Wedding Gown',
    'Shirt',
    'Coat',
    'Alteration',
    'Other',
]


def portal_home(request):
    """Render the public landing page of the sewing shop."""
    return render(request, 'portal/home.html')


def portal_register(request):
    """Register a new customer account from the public portal.

    The function validates the form server side, refuses duplicate emails,
    enforces a minimum password length and creates both a ``User`` and a
    ``Customer`` record before logging the user in.
    """
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect('portal_dashboard')

    if request.method != 'POST':
        return render(request, 'portal/register.html')

    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    email = _normalise_email(request.POST.get('email'))
    phone = request.POST.get('phone', '').strip()
    address = request.POST.get('address', '').strip()
    password1 = request.POST.get('password1', '')
    password2 = request.POST.get('password2', '')

    errors = []
    if not first_name or not last_name:
        errors.append('First and last name are required.')
    if not email:
        errors.append('Email is required.')
    elif (
        User.objects.filter(username=email).exists()
        or User.objects.filter(email=email).exists()
    ):
        errors.append('An account with this email already exists.')
    if password1 != password2:
        errors.append('Passwords do not match.')
    if len(password1) < MIN_PASSWORD_LENGTH:
        errors.append(
            f'The password must be at least {MIN_PASSWORD_LENGTH} characters long.'
        )

    if errors:
        return render(
            request,
            'portal/register.html',
            {'errors': errors, 'data': request.POST},
        )

    user = User.objects.create_user(
        username=email,
        email=email,
        password=password1,
        first_name=first_name,
        last_name=last_name,
    )
    Customer.objects.create(
        user=user,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        address=address,
    )
    login(request, user)
    messages.success(
        request,
        f'Welcome, {first_name}. Your account has been created.',
    )
    return redirect('portal_dashboard')


def portal_login(request):
    """Authenticate a customer through the public portal."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard')
        return redirect('portal_dashboard')

    if request.method != 'POST':
        return render(request, 'portal/login.html')

    email = _normalise_email(request.POST.get('email'))
    password = request.POST.get('password', '')
    user = authenticate(request, username=email, password=password)
    if not user:
        return render(
            request,
            'portal/login.html',
            {'error': 'The email or password is invalid.', 'email': email},
        )

    login(request, user)
    if user.is_staff:
        return redirect('dashboard')
    return redirect('portal_dashboard')


def portal_logout(request):
    """Log the customer out and return them to the public landing page."""
    logout(request)
    return redirect('portal_home')


def portal_dashboard(request):
    """Show the customer their active and completed orders."""
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('dashboard')

    customer = _customer_for_user(request.user)
    if not customer:
        return redirect('portal_login')

    orders = CustomerOrder.objects.filter(customer=customer).order_by('-order_date')
    active_orders = orders.exclude(status__in=CLOSED_ORDER_STATUSES)
    completed_orders = orders.filter(status__in=CLOSED_ORDER_STATUSES)

    return render(
        request,
        'portal/dashboard.html',
        {
            'customer': customer,
            'active_orders': active_orders,
            'completed_orders': completed_orders,
        },
    )


def portal_order_detail(request, pk):
    """Show a customer the production timeline of one of their orders."""
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('order_detail', pk=pk)

    customer = _customer_for_user(request.user)
    if not customer:
        return redirect('portal_login')

    order = get_object_or_404(CustomerOrder, pk=pk, customer=customer)
    items = order.items.prefetch_related(
        'tickets__current_stage', 'tickets__status_history__stage'
    ).all()
    delivery = getattr(order, 'delivery', None)

    return render(
        request,
        'portal/order_detail.html',
        {'order': order, 'items': items, 'delivery': delivery},
    )


def portal_book(request):
    """Accept a booking submitted by a logged in customer.

    The view validates the required fields and, on success, creates an order
    in ``received`` state together with one order item that captures the
    fabric and color the customer requested. Pricing is left at zero so the
    receptionist can adjust it on follow up.
    """
    if not request.user.is_authenticated:
        return redirect('portal_login')
    if request.user.is_staff:
        return redirect('dashboard')

    customer = _customer_for_user(request.user)
    if not customer:
        return redirect('portal_login')

    if request.method != 'POST':
        return render(
            request,
            'portal/book.html',
            {'garment_types': PORTAL_GARMENT_TYPES},
        )

    due_date = request.POST.get('due_date')
    notes = request.POST.get('notes', '').strip()
    priority = request.POST.get('priority', 'normal')
    garment_type = request.POST.get('garment_type', '').strip()
    fabric = request.POST.get('fabric', '').strip()
    color = request.POST.get('color', '').strip()
    special_instructions = request.POST.get('special_instructions', '').strip()
    try:
        quantity = int(request.POST.get('quantity', DEFAULT_PORTAL_QUANTITY))
    except (TypeError, ValueError):
        quantity = DEFAULT_PORTAL_QUANTITY
    if quantity < 1:
        quantity = DEFAULT_PORTAL_QUANTITY

    if not due_date or not garment_type:
        return render(
            request,
            'portal/book.html',
            {
                'error': 'Please fill in every required field.',
                'data': request.POST,
                'garment_types': PORTAL_GARMENT_TYPES,
            },
        )

    order = CustomerOrder.objects.create(
        customer=customer,
        due_date=due_date,
        priority=priority,
        status=ORDER_STATUS_RECEIVED,
        payment_status=PAYMENT_STATUS_UNPAID,
        notes=notes,
    )
    OrderItem.objects.create(
        order=order,
        garment_type=garment_type,
        fabric=fabric,
        color=color,
        quantity=quantity,
        special_instructions=special_instructions,
        unit_price=Decimal('0.00'),
    )
    messages.success(
        request,
        f'Your booking #{order.pk} has been submitted. '
        'A member of staff will contact you shortly to confirm details and pricing.',
    )
    return redirect('portal_order_detail', pk=order.pk)


def portal_profile(request):
    """Allow a customer to update their phone, address and notes."""
    if not request.user.is_authenticated:
        return redirect('portal_login')

    customer = _customer_for_user(request.user)
    if not customer:
        return redirect('portal_login')

    if request.method == 'POST':
        customer.phone = request.POST.get('phone', '').strip()
        customer.address = request.POST.get('address', '').strip()
        customer.notes = request.POST.get('notes', '').strip()
        customer.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('portal_profile')

    return render(request, 'portal/profile.html', {'customer': customer})


# ---------------------------------------------------------------------------
# Employee portal.
# ---------------------------------------------------------------------------

def emp_login(request):
    """Authenticate an employee through the staff portal."""
    if request.user.is_authenticated:
        employee = _employee_for_user(request.user)
        if employee:
            return redirect('emp_dashboard')
        if request.user.is_staff:
            return redirect('dashboard')

    if request.method != 'POST':
        return render(request, 'employee/login.html')

    email = _normalise_email(request.POST.get('email'))
    password = request.POST.get('password', '')
    user = authenticate(request, username=email, password=password)
    if not user:
        return render(
            request,
            'employee/login.html',
            {'error': 'The email or password is invalid.', 'email': email},
        )

    employee = _employee_for_user(user)
    if employee:
        login(request, user)
        return redirect('emp_dashboard')

    if user.is_staff:
        login(request, user)
        return redirect('dashboard')

    return render(
        request,
        'employee/login.html',
        {
            'error': (
                'No employee account is linked to this user. '
                'Please contact your manager.'
            ),
            'email': email,
        },
    )


def emp_logout(request):
    """Log the employee out and return them to the staff portal login page."""
    logout(request)
    return redirect('emp_login')


def emp_required(view_func):
    """Decorate a view so that it requires an authenticated employee.

    The wrapper redirects unauthenticated users to the login page, redirects
    staff who are not employees to the staff dashboard, and otherwise injects
    the resolved ``Employee`` instance as a keyword argument.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('emp_login')
        employee = _employee_for_user(request.user)
        if not employee:
            if request.user.is_staff:
                return redirect('dashboard')
            return redirect('emp_login')
        return view_func(request, *args, employee=employee, **kwargs)
    return wrapper


@emp_required
def emp_dashboard(request, employee):
    """Show the employee their open tickets and the shop wide pipeline."""
    today = timezone.now().date()

    my_assignments = TaskAssignment.objects.filter(
        employee=employee, assignment_status=ASSIGNMENT_STATUS_CURRENT
    ).values_list('ticket_id', flat=True)

    my_tickets_qs = (
        WorkTicket.objects
        .filter(pk__in=my_assignments)
        .exclude(status=TICKET_STATUS_COMPLETED)
        .select_related('current_stage', 'order_item__order__customer')
        .order_by('priority', 'deadline')[:EMPLOYEE_DASHBOARD_TICKETS_LIMIT]
    )

    my_open = WorkTicket.objects.filter(pk__in=my_assignments).exclude(
        status=TICKET_STATUS_COMPLETED
    ).count()
    my_urgent = WorkTicket.objects.filter(
        pk__in=my_assignments, priority='urgent'
    ).exclude(status=TICKET_STATUS_COMPLETED).count()
    my_done_today = TicketStatusHistory.objects.filter(
        ticket__in=my_assignments,
        changed_at__date=today,
        stage__stage_name__icontains='quality',
    ).count()
    shop_overdue = CustomerOrder.objects.filter(
        due_date__lt=today
    ).exclude(status__in=CLOSED_ORDER_STATUSES).count()

    pipeline = ProductionStage.objects.annotate(
        ticket_count=Count(
            'active_tickets',
            filter=Q(active_tickets__status__in=ACTIVE_TICKET_STATUSES),
        )
    ).order_by('stage_order')

    return render(
        request,
        'employee/dashboard.html',
        {
            'employee': employee,
            'my_tickets': my_tickets_qs,
            'my_open': my_open,
            'my_urgent': my_urgent,
            'my_done_today': my_done_today,
            'shop_overdue': shop_overdue,
            'pipeline': pipeline,
        },
    )


@emp_required
def emp_my_tickets(request, employee):
    """List every ticket currently assigned to the logged in employee."""
    my_assignments = TaskAssignment.objects.filter(
        employee=employee, assignment_status=ASSIGNMENT_STATUS_CURRENT
    ).values_list('ticket_id', flat=True)
    tickets = (
        WorkTicket.objects
        .filter(pk__in=my_assignments)
        .select_related('current_stage', 'order_item__order__customer')
        .order_by('priority', 'deadline')
    )
    return render(
        request,
        'employee/my_tickets.html',
        {'employee': employee, 'tickets': tickets},
    )


@emp_required
def emp_all_tickets(request, employee):
    """List every ticket in the shop, filterable by status and priority."""
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
    return render(
        request,
        'employee/all_tickets.html',
        {'employee': employee, 'tickets': tickets},
    )


@emp_required
def emp_ticket_detail(request, pk, employee):
    """Show one ticket from the employee perspective."""
    ticket = get_object_or_404(WorkTicket, pk=pk)
    history = (
        ticket.status_history
        .select_related('stage', 'changed_by')
        .order_by('changed_at')
    )
    stages = ProductionStage.objects.order_by('stage_order')
    incidents = ticket.damage_incidents.all()
    return render(
        request,
        'employee/ticket_detail.html',
        {
            'employee': employee,
            'ticket': ticket,
            'history': history,
            'stages': stages,
            'incidents': incidents,
        },
    )


@emp_required
def emp_update_stage(request, pk, employee):
    """Move a ticket to a new stage from the employee portal."""
    if request.method != 'POST':
        return redirect('emp_ticket_detail', pk=pk)

    ticket = get_object_or_404(WorkTicket, pk=pk)
    stage_id = request.POST.get('stage')
    comment = request.POST.get('comment', '').strip()
    try:
        stage = ProductionStage.objects.get(pk=stage_id)
    except ProductionStage.DoesNotExist:
        messages.error(request, 'The selected stage is invalid.')
        return redirect('emp_ticket_detail', pk=pk)

    ticket.current_stage = stage
    if ticket.status in (TICKET_STATUS_OPEN, TICKET_STATUS_ASSIGNED):
        ticket.status = TICKET_STATUS_IN_PROGRESS
    ticket.save()

    TicketStatusHistory.objects.create(
        ticket=ticket,
        stage=stage,
        changed_by=employee,
        comment=comment or f'Stage updated by {employee.full_name}.',
    )
    messages.success(request, f'Stage updated to "{stage.stage_name}".')
    return redirect('emp_ticket_detail', pk=pk)


@emp_required
def emp_complete_ticket(request, pk, employee):
    """Mark a ticket as completed from the employee portal."""
    if request.method != 'POST':
        return redirect('emp_ticket_detail', pk=pk)

    ticket = get_object_or_404(WorkTicket, pk=pk)
    comment = request.POST.get('comment', '').strip()
    ticket.status = TICKET_STATUS_COMPLETED
    ticket.save()

    last_stage = ProductionStage.objects.order_by('-stage_order').first()
    if last_stage:
        TicketStatusHistory.objects.create(
            ticket=ticket,
            stage=last_stage,
            changed_by=employee,
            comment=comment or f'Completed by {employee.full_name}.',
        )

    _propagate_item_completion(ticket.order_item)

    messages.success(request, f'Ticket {ticket.ticket_code} marked as completed.')
    return redirect('emp_my_tickets')


@emp_required
def emp_orders(request, employee):
    """List the active orders that the employee can pick up work from."""
    orders = (
        CustomerOrder.objects
        .exclude(status__in=CLOSED_ORDER_STATUSES)
        .select_related('customer')
        .order_by('due_date')
    )
    return render(
        request,
        'employee/orders.html',
        {'employee': employee, 'orders': orders},
    )


@emp_required
def emp_profile(request, employee):
    """Show the employee their own staff profile."""
    return render(request, 'employee/profile.html', {'employee': employee})
