"""Single source of truth for state transitions.

Views, forms, admin actions, and management commands MUST go through
``transition`` / ``transition_request`` / ``schedule_delivery`` /
``confirm_delivery`` etc. instead of writing to ``status`` directly.

Every transition runs the cascades, writes an AuditLog row, and emits
the relevant event so notifications and counters update consistently.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from shop import events
from shop.services import audit


# ── Transition tables ─────────────────────────────────────────────────


ORDER_TRANSITIONS: dict[str, set[str]] = {
    'draft':              {'received', 'cancelled'},
    'received':           {'in_production', 'cancelled'},
    'in_production':      {'completed', 'cancelled'},
    'completed':          {'ready_for_delivery', 'cancelled'},
    'ready_for_delivery': {'delivered', 'cancelled'},
    'delivered':          set(),
    'cancelled':          set(),
}


TICKET_TRANSITIONS: dict[str, set[str]] = {
    'open':         {'assigned', 'in_progress', 'cancelled'},
    'assigned':     {'in_progress', 'blocked', 'cancelled'},
    'in_progress':  {'completed', 'blocked', 'cancelled'},
    'blocked':      {'in_progress', 'cancelled'},
    'completed':    set(),
    'cancelled':    set(),
}


ITEM_TRANSITIONS: dict[str, set[str]] = {
    'pending':         {'in_progress', 'completed', 'cancelled'},
    'in_progress':     {'completed', 'damaged', 'remake_required', 'cancelled'},
    'damaged':         {'remake_required', 'in_progress', 'cancelled'},
    'remake_required': {'in_progress', 'cancelled'},
    'completed':       {'delivered', 'cancelled'},
    'delivered':       set(),
    'cancelled':       set(),
}


REQUEST_TRANSITIONS: dict[str, set[str]] = {
    'pending':   {'approved', 'rejected', 'cancelled'},
    'approved':  {'converted', 'fulfilled', 'cancelled'},
    'rejected':  set(),
    'converted': {'fulfilled', 'cancelled'},
    'fulfilled': set(),
    'cancelled': set(),
}


SUPPLIER_ORDER_TRANSITIONS: dict[str, set[str]] = {
    'draft':     {'placed', 'cancelled'},
    'placed':    {'shipped', 'received', 'cancelled'},
    'shipped':   {'received', 'cancelled'},
    'received':  set(),
    'cancelled': set(),
}


# ── Errors ─────────────────────────────────────────────────────────────


class WorkflowError(Exception):
    """Any workflow rule violation."""


class InvalidTransition(WorkflowError):
    pass


class TransitionBlocked(WorkflowError):
    pass


# ── Helpers ────────────────────────────────────────────────────────────


def _allowed(table: dict[str, set[str]], obj_status: str) -> set[str]:
    return table.get(obj_status, set())


def next_states(obj) -> list[tuple[str, str, str | None]]:
    """Return [(value, label, blocking_reason_or_none), ...] for `obj`."""
    from shop.models import (
        CustomerOrder, WorkTicket, OrderItem, MaterialRequest, SupplierOrder,
    )
    if isinstance(obj, CustomerOrder):
        table, choices = ORDER_TRANSITIONS, dict(CustomerOrder.STATUS_CHOICES)
    elif isinstance(obj, WorkTicket):
        table, choices = TICKET_TRANSITIONS, dict(WorkTicket.TICKET_STATUS_CHOICES)
    elif isinstance(obj, OrderItem):
        table, choices = ITEM_TRANSITIONS, dict(OrderItem.ITEM_STATUS_CHOICES)
    elif isinstance(obj, MaterialRequest):
        table, choices = REQUEST_TRANSITIONS, dict(MaterialRequest.STATUS_CHOICES)
    elif isinstance(obj, SupplierOrder):
        table, choices = SUPPLIER_ORDER_TRANSITIONS, dict(SupplierOrder.STATUS_CHOICES)
    else:
        return []
    out = []
    for target in _allowed(table, obj.status):
        out.append((target, choices.get(target, target), blocking_reason(obj, target)))
    return out


def blocking_reason(obj, target: str) -> str | None:
    """Return a human-readable reason a transition would currently fail, or None."""
    from shop.models import CustomerOrder, WorkTicket
    if isinstance(obj, CustomerOrder):
        if target == 'ready_for_delivery':
            unresolved = obj.items.filter(damage_incidents__is_resolved=False).exists()
            if unresolved:
                return 'There are unresolved damage incidents.'
            unfinished = obj.items.exclude(item_status__in=['completed', 'cancelled', 'delivered']).exists()
            if unfinished:
                return 'Not all items are completed yet.'
        if target == 'delivered':
            try:
                delivery = obj.delivery
            except Exception:
                delivery = None
            if delivery is None:
                return 'No delivery has been scheduled.'
            if not delivery.is_delivered:
                return 'Delivery exists but is not confirmed yet.'
    if isinstance(obj, WorkTicket):
        if target == 'completed':
            if obj.damage_incidents.filter(is_resolved=False).exists():
                return 'Resolve open damage incidents before completing.'
    return None


# ── Core transition ───────────────────────────────────────────────────


@dataclass(slots=True)
class TransitionResult:
    obj: object
    from_status: str
    to_status: str


def _table_for(obj) -> dict[str, set[str]]:
    from shop.models import (
        CustomerOrder, WorkTicket, OrderItem, MaterialRequest, SupplierOrder,
    )
    if isinstance(obj, CustomerOrder):
        return ORDER_TRANSITIONS
    if isinstance(obj, WorkTicket):
        return TICKET_TRANSITIONS
    if isinstance(obj, OrderItem):
        return ITEM_TRANSITIONS
    if isinstance(obj, MaterialRequest):
        return REQUEST_TRANSITIONS
    if isinstance(obj, SupplierOrder):
        return SUPPLIER_ORDER_TRANSITIONS
    raise WorkflowError(f'No transition table for {type(obj).__name__}')


def _event_name_for(obj, to_status: str) -> str:
    from shop.models import (
        CustomerOrder, WorkTicket, MaterialRequest, SupplierOrder,
    )
    if isinstance(obj, CustomerOrder):
        if to_status == 'ready_for_delivery':
            return events.ORDER_READY
        if to_status == 'delivered':
            return events.ORDER_DELIVERED
        if to_status == 'cancelled':
            return events.ORDER_CANCELLED
        return events.ORDER_TRANSITION
    if isinstance(obj, WorkTicket):
        if to_status == 'blocked':
            return events.TICKET_BLOCKED
        return events.TICKET_TRANSITION
    if isinstance(obj, MaterialRequest):
        return {
            'approved':  events.MATERIAL_APPROVED,
            'rejected':  events.MATERIAL_REJECTED,
            'converted': events.MATERIAL_CONVERTED,
            'fulfilled': events.MATERIAL_FULFILLED,
        }.get(to_status, 'material.transition')
    if isinstance(obj, SupplierOrder):
        return {
            'placed':   events.SUPPLIER_ORDER_PLACED,
            'received': events.SUPPLIER_ORDER_RECEIVED,
        }.get(to_status, 'supplier_order.transition')
    return 'workflow.transition'


@transaction.atomic
def transition(obj, *, to: str, actor=None, comment: str = '', force: bool = False) -> TransitionResult:
    """Validate, persist, audit, cascade, emit. The only legal status writer."""
    current = getattr(obj, 'status', None) or getattr(obj, 'item_status', None)
    is_item = hasattr(obj, 'item_status') and not hasattr(obj, 'status')
    table = _table_for(obj)
    if to == current:
        return TransitionResult(obj=obj, from_status=current, to_status=to)
    if not force and to not in _allowed(table, current):
        raise InvalidTransition(
            f'{type(obj).__name__} cannot move {current!r} → {to!r}'
        )
    reason = blocking_reason(obj, to)
    if reason and not force:
        raise TransitionBlocked(reason)

    before = {'status': current}
    if is_item:
        obj.item_status = to
        obj.save(update_fields=['item_status'])
    else:
        obj.status = to
        update_fields = ['status']
        if hasattr(obj, 'updated_at'):
            update_fields.append('updated_at')
        obj.save(update_fields=update_fields)
    after = {'status': to}

    audit.log(
        actor=actor, action=f'{type(obj).__name__.lower()}.transition',
        target=obj, before=before, after=after,
        message=comment or f'{current} → {to}',
    )

    # Cascades
    _cascade_after_transition(obj, from_status=current, to_status=to, actor=actor, comment=comment)

    # Event
    events.emit(_event_name_for(obj, to), target=obj, actor=actor, payload={
        'from': current, 'to': to, 'comment': comment,
    })

    return TransitionResult(obj=obj, from_status=current, to_status=to)


def _cascade_after_transition(obj, *, from_status, to_status, actor, comment):
    from shop.models import (
        CustomerOrder, WorkTicket,
    )

    # Ticket completed → re-evaluate item, then order
    if isinstance(obj, WorkTicket) and to_status == 'completed':
        item = obj.order_item
        outstanding = item.tickets.exclude(status__in=['completed', 'cancelled']).exists()
        if not outstanding and item.item_status not in ('completed', 'delivered'):
            transition(item, to='completed', actor=actor, comment='All tickets completed.')
        order = item.order
        order_outstanding = order.items.exclude(
            item_status__in=['completed', 'cancelled', 'delivered']
        ).exists()
        if not order_outstanding and order.status == 'in_production':
            transition(order, to='completed', actor=actor,
                       comment='All items completed.')

    # Ticket blocked → set order item flag visible to staff
    if isinstance(obj, WorkTicket) and to_status == 'blocked':
        item = obj.order_item
        if item.item_status == 'in_progress':
            try:
                transition(item, to='damaged', actor=actor, comment='Ticket blocked.')
            except (InvalidTransition, TransitionBlocked):
                pass

    # Order delivered → mark items delivered (cascade only legal targets)
    if isinstance(obj, CustomerOrder) and to_status == 'delivered':
        for item in obj.items.exclude(item_status='delivered'):
            try:
                transition(item, to='delivered', actor=actor, comment='Parent order delivered.')
            except (InvalidTransition, TransitionBlocked):
                # If not legal, force to keep state consistent.
                item.item_status = 'delivered'
                item.save(update_fields=['item_status'])


# ── Production stage advancement ─────────────────────────────────────


@transaction.atomic
def advance_stage(ticket, *, to_stage, actor=None, comment: str = '', force_skip: bool = False):
    """Move a ticket to a production stage. Only forward (or +1), unless force_skip."""
    from shop.models import ProductionStage, TicketStatusHistory
    if not isinstance(to_stage, ProductionStage):
        to_stage = ProductionStage.objects.get(pk=to_stage)
    current = ticket.current_stage
    if current and to_stage.stage_order < current.stage_order and not force_skip:
        raise WorkflowError('Cannot move backwards through production stages without override.')
    if (
        current
        and to_stage.stage_order > current.stage_order + 1
        and not force_skip
    ):
        raise WorkflowError('Skipping more than one stage requires an explicit override.')

    before = {'stage': current.stage_name if current else None, 'status': ticket.status}
    ticket.current_stage = to_stage
    if ticket.status in ('open', 'assigned'):
        ticket.status = 'in_progress'
    ticket.save(update_fields=['current_stage', 'status', 'updated_at'])
    TicketStatusHistory.objects.create(
        ticket=ticket, stage=to_stage,
        changed_by=getattr(actor, 'employee_set', None) and actor.employee_set.first()
                   or _employee_of(actor),
        comment=comment or f'Advanced to {to_stage.stage_name}',
    )
    audit.log(
        actor=actor, action='ticket.stage_advanced', target=ticket,
        before=before, after={'stage': to_stage.stage_name, 'status': ticket.status},
        message=comment or f'Stage → {to_stage.stage_name}',
    )
    events.emit(events.TICKET_STAGE_ADVANCED, target=ticket, actor=actor, payload={
        'stage': to_stage.stage_name,
        'stage_order': to_stage.stage_order,
    })
    return ticket


def _employee_of(user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    from shop.models import Employee
    return Employee.objects.filter(user=user).first()


# ── Delivery helpers (gates Delivery creation) ────────────────────────


@transaction.atomic
def schedule_delivery(order, *, delivery_date, delivery_method, received_by='', comments='', actor=None):
    """Create or update a Delivery row. Refuses unless order is ready_for_delivery."""
    from shop.models import Delivery
    if order.status != 'ready_for_delivery':
        raise TransitionBlocked(
            f"Delivery can only be scheduled when the order is 'Ready for Delivery'. "
            f"Current status: {order.get_status_display()}."
        )
    delivery, created = Delivery.objects.get_or_create(
        order=order,
        defaults={
            'delivery_date': delivery_date,
            'delivery_method': delivery_method,
            'received_by': received_by,
            'comments': comments,
            'is_delivered': False,
        },
    )
    if not created:
        before = {
            'delivery_date': delivery.delivery_date,
            'delivery_method': delivery.delivery_method,
            'received_by': delivery.received_by,
        }
        delivery.delivery_date = delivery_date
        delivery.delivery_method = delivery_method
        delivery.received_by = received_by
        delivery.comments = comments
        delivery.save(update_fields=['delivery_date', 'delivery_method', 'received_by', 'comments'])
        audit.log(
            actor=actor, action='delivery.updated', target=delivery,
            before=before, after={
                'delivery_date': delivery_date, 'delivery_method': delivery_method,
                'received_by': received_by,
            },
            message='Delivery details updated',
        )
    else:
        audit.log(
            actor=actor, action='delivery.scheduled', target=delivery,
            before={}, after={'delivery_date': delivery_date},
            message='Delivery scheduled',
        )
    events.emit(events.DELIVERY_SCHEDULED, target=order, actor=actor, payload={
        'delivery_date': str(delivery_date),
        'method': delivery_method,
    })
    return delivery


@transaction.atomic
def confirm_delivery(order, *, actor=None, received_by: str | None = None):
    from shop.models import Delivery
    delivery = Delivery.objects.filter(order=order).first()
    if delivery is None:
        raise TransitionBlocked('No delivery is scheduled for this order yet.')
    before = {'is_delivered': delivery.is_delivered}
    delivery.is_delivered = True
    if received_by:
        delivery.received_by = received_by
    delivery.delivery_date = timezone.now().date()
    delivery.save(update_fields=['is_delivered', 'received_by', 'delivery_date'])
    audit.log(
        actor=actor, action='delivery.confirmed', target=delivery,
        before=before, after={'is_delivered': True},
        message=f'Confirmed delivery for order #{order.pk}',
    )
    events.emit(events.DELIVERY_CONFIRMED, target=order, actor=actor, payload={})
    transition(order, to='delivered', actor=actor, comment='Delivery confirmed.')
    return delivery


# ── Material request lifecycle ───────────────────────────────────────


@transaction.atomic
def transition_request(req, *, to: str, actor=None, comment: str = '', supplier_order=None):
    """Transition a MaterialRequest with the same engine."""
    if to not in _allowed(REQUEST_TRANSITIONS, req.status):
        raise InvalidTransition(f'MaterialRequest cannot move {req.status!r} → {to!r}')
    before = {'status': req.status, 'supplier_order': req.supplier_order_id}
    req.status = to
    req.decided_by = actor if actor is not None else req.decided_by
    req.decided_at = timezone.now()
    if comment:
        req.decision_notes = (req.decision_notes + ('\n' if req.decision_notes else '') + comment)[:2000]
    update_fields = ['status', 'decided_by', 'decided_at', 'decision_notes']
    if to == 'converted':
        if supplier_order is None:
            raise WorkflowError('Cannot convert a material request without a supplier order.')
        req.supplier_order = supplier_order
        update_fields.append('supplier_order')
    if to == 'fulfilled':
        req.fulfilled_at = timezone.now()
        update_fields.append('fulfilled_at')
    req.save(update_fields=update_fields)
    audit.log(
        actor=actor, action=f'materialrequest.{to}', target=req,
        before=before, after={'status': to, 'supplier_order': req.supplier_order_id},
        message=comment or f'{before["status"]} → {to}',
    )
    events.emit(_event_name_for(req, to), target=req, actor=actor, payload={
        'from': before['status'], 'to': to, 'comment': comment,
    })
    return req


# ── Material consumption (decrements stock + audit) ──────────────────


@transaction.atomic
def consume_material(*, order_item, material, quantity, actor=None, notes=''):
    from shop.models import OrderItemMaterial
    consumption = OrderItemMaterial.objects.create(
        order_item=order_item, material=material,
        quantity=quantity, unit_cost_snapshot=material.unit_cost,
        notes=notes,
    )
    before = {'stock_on_hand': str(material.stock_on_hand)}
    material.stock_on_hand = (material.stock_on_hand or 0) - quantity
    material.save(update_fields=['stock_on_hand'])
    audit.log(
        actor=actor, action='material.consumed', target=material,
        before=before, after={'stock_on_hand': str(material.stock_on_hand)},
        message=f'-{quantity} on order item #{order_item.pk}',
    )
    if material.is_low_stock:
        events.emit(events.MATERIAL_LOW, target=material, actor=actor, payload={
            'stock_on_hand': str(material.stock_on_hand),
            'threshold': str(material.low_stock_threshold),
        })
    return consumption
