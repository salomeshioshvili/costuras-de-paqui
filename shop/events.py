"""Tiny synchronous event bus.

Anything that wants to react to a domain event subscribes via @on(name).
Views and services emit through events.emit(...). Notifications, audit
log, and counters all key off this module so that nothing is sent or
recorded from inside a view directly.
"""
from collections import defaultdict
from typing import Callable, Iterable, Any


# ── Event names (strings used everywhere) ───────────────────────────────
ORDER_CREATED          = 'order.created'
ORDER_TRANSITION       = 'order.transition'
ORDER_READY            = 'order.ready_for_delivery'
ORDER_DELIVERED        = 'order.delivered'
ORDER_OVERDUE          = 'order.overdue'
ORDER_CANCELLED        = 'order.cancelled'

TICKET_TRANSITION      = 'ticket.transition'
TICKET_STAGE_ADVANCED  = 'ticket.stage_advanced'
TICKET_ASSIGNED        = 'ticket.assigned'
TICKET_BLOCKED         = 'ticket.blocked'

PAYMENT_RECEIVED       = 'payment.received'
PAYMENT_REMINDER       = 'payment.reminder'
PAYMENT_REFUNDED       = 'payment.refunded'

DELIVERY_SCHEDULED     = 'delivery.scheduled'
DELIVERY_CONFIRMED     = 'delivery.confirmed'
PICKUP_REMINDER        = 'pickup.reminder'

FITTING_REMINDER       = 'appointment.fitting_reminder'
APPOINTMENT_REQUESTED  = 'appointment.requested'
APPOINTMENT_CONFIRMED  = 'appointment.confirmed'

MATERIAL_REQUESTED     = 'material.requested'
MATERIAL_APPROVED      = 'material.approved'
MATERIAL_REJECTED      = 'material.rejected'
MATERIAL_CONVERTED     = 'material.converted'
MATERIAL_FULFILLED     = 'material.fulfilled'
MATERIAL_LOW           = 'material.low_stock'

SUPPLIER_ORDER_PLACED  = 'supplier_order.placed'
SUPPLIER_ORDER_RECEIVED = 'supplier_order.received'

LEAD_RECEIVED          = 'lead.received'
LEAD_CONVERTED         = 'lead.converted'

INCIDENT_REPORTED      = 'incident.reported'
INCIDENT_RESOLVED      = 'incident.resolved'


_subscribers: dict[str, list[Callable[..., Any]]] = defaultdict(list)


def on(event_name: str):
    """Decorator: subscribe a callable to an event."""
    def _decorator(fn):
        _subscribers[event_name].append(fn)
        return fn
    return _decorator


def emit(event_name: str, *, target=None, actor=None, payload: dict | None = None):
    """Fire an event; every subscriber runs synchronously.

    Subscribers must accept (event_name, target=, actor=, payload=).
    Errors in one subscriber never break the others.
    """
    payload = payload or {}
    for subscriber in list(_subscribers.get(event_name, [])):
        try:
            subscriber(event_name, target=target, actor=actor, payload=payload)
        except Exception as exc:
            import logging
            logging.getLogger('shop.events').exception(
                'Subscriber %s failed on %s: %s', subscriber, event_name, exc
            )


def subscribers_for(event_name: str) -> Iterable[Callable]:
    return tuple(_subscribers.get(event_name, ()))
