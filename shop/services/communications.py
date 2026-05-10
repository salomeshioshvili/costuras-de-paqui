"""Notification dispatcher.

Subscribes to events.* and writes a NotificationLog row per channel.
Real channel sends are delegated to providers; the default providers
write to the console + log so the system always works without API keys.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from shop import events
from shop.models import (
    Appointment, CustomerOrder, MaterialRequest, Material,
    NotificationLog, NotificationPreference, Payment,
)
from shop.providers import email as email_provider
from shop.providers import sms as sms_provider
from shop.providers import whatsapp as whatsapp_provider


log = logging.getLogger('shop.communications')


# ── Copy table ────────────────────────────────────────────────────────


CATALOG = {
    events.ORDER_READY: {
        'es': ('Tu pedido está listo', 'Hola {name}, tu pedido #{order_id} ya está terminado y listo para recoger.'),
        'en': ('Your order is ready', 'Hi {name}, your order #{order_id} is finished and ready to pick up.'),
        'fr': ('Votre commande est prête', 'Bonjour {name}, votre commande #{order_id} est prête.'),
    },
    events.ORDER_DELIVERED: {
        'es': ('Pedido entregado', 'Hola {name}, hemos confirmado la entrega de tu pedido #{order_id}.'),
        'en': ('Order delivered', 'Hi {name}, we confirmed delivery of your order #{order_id}.'),
        'fr': ('Commande livrée', 'Bonjour {name}, livraison confirmée pour la commande #{order_id}.'),
    },
    events.PAYMENT_RECEIVED: {
        'es': ('Pago recibido', 'Hola {name}, hemos recibido tu pago de {amount} {currency} para el pedido #{order_id}.'),
        'en': ('Payment received', 'Hi {name}, we received your payment of {amount} {currency} for order #{order_id}.'),
        'fr': ('Paiement reçu', 'Bonjour {name}, paiement de {amount} {currency} reçu pour la commande #{order_id}.'),
    },
    events.PAYMENT_REMINDER: {
        'es': ('Recordatorio de pago', 'Hola {name}, queda un saldo pendiente de {amount} {currency} en el pedido #{order_id}.'),
        'en': ('Payment reminder', 'Hi {name}, there is an outstanding balance of {amount} {currency} on order #{order_id}.'),
        'fr': ('Rappel de paiement', 'Bonjour {name}, solde en attente de {amount} {currency} sur la commande #{order_id}.'),
    },
    events.PICKUP_REMINDER: {
        'es': ('Recordatorio de recogida', 'Hola {name}, no olvides recoger tu pedido #{order_id}.'),
        'en': ('Pickup reminder', 'Hi {name}, don\'t forget to pick up your order #{order_id}.'),
        'fr': ('Rappel de retrait', 'Bonjour {name}, votre commande #{order_id} vous attend.'),
    },
    events.ORDER_OVERDUE: {
        'es': ('Pedido vencido', 'Aviso interno: el pedido #{order_id} está vencido.'),
        'en': ('Order overdue', 'Internal alert: order #{order_id} is overdue.'),
        'fr': ('Commande en retard', 'Alerte interne : commande #{order_id} en retard.'),
    },
    events.FITTING_REMINDER: {
        'es': ('Recordatorio de prueba', 'Hola {name}, te recordamos tu prueba el {when} en {place}.'),
        'en': ('Fitting reminder', 'Hi {name}, reminder of your fitting on {when} at {place}.'),
        'fr': ('Rappel d\'essayage', 'Bonjour {name}, rappel de votre essayage le {when} à {place}.'),
    },
    events.APPOINTMENT_REQUESTED: {
        'es': ('Cita recibida', 'Recibimos tu cita {kind}. Te confirmaremos pronto.'),
        'en': ('Appointment received', 'We got your {kind} request. We\'ll confirm shortly.'),
        'fr': ('Rendez-vous reçu', 'Nous avons reçu votre demande de {kind}. Confirmation à venir.'),
    },
    events.MATERIAL_LOW: {
        'es': ('Stock bajo', 'Material {material} ha bajado de su umbral ({stock} restante).'),
        'en': ('Low stock', 'Material {material} dropped below threshold ({stock} left).'),
        'fr': ('Stock bas', 'Le matériau {material} est sous le seuil ({stock} restant).'),
    },
    events.MATERIAL_APPROVED: {
        'es': ('Solicitud aprobada', 'Tu solicitud de {material} ha sido aprobada.'),
        'en': ('Request approved', 'Your request for {material} was approved.'),
        'fr': ('Demande approuvée', 'Votre demande pour {material} a été approuvée.'),
    },
    events.MATERIAL_REJECTED: {
        'es': ('Solicitud rechazada', 'Tu solicitud de {material} fue rechazada.'),
        'en': ('Request rejected', 'Your request for {material} was rejected.'),
        'fr': ('Demande refusée', 'Votre demande pour {material} a été refusée.'),
    },
    events.LEAD_RECEIVED: {
        'es': ('Nueva consulta', 'Nueva consulta de intake recibida.'),
        'en': ('New intake', 'A new intake submission was received.'),
        'fr': ('Nouvelle demande', 'Une nouvelle demande a été reçue.'),
    },
}


# ── Provider lookup ──────────────────────────────────────────────────


_provider_lookup = {
    'email': email_provider,
    'sms': sms_provider,
    'whatsapp': whatsapp_provider,
}


def _provider_for(channel: str):
    mod = _provider_lookup.get(channel)
    return mod.get_provider() if mod else None


def _channels_for_user(user) -> list[str]:
    if user is None:
        return ['inapp']
    prefs = NotificationPreference.objects.filter(user=user)
    if not prefs.exists():
        return ['inapp', 'email']
    return [p.channel for p in prefs if p.enabled]


def _lookup_copy(event_name: str, language: str) -> tuple[str, str]:
    table = CATALOG.get(event_name)
    if not table:
        return (event_name.replace('_', ' ').title(),
                f'Event {event_name} fired.')
    if language in table:
        return table[language]
    if 'en' in table:
        return table['en']
    return next(iter(table.values()))


# ── Public dispatcher ────────────────────────────────────────────────


def notify(*, event: str, recipient_user=None, recipient_email='', recipient_phone='',
           language='es', payload=None) -> list[NotificationLog]:
    payload = payload or {}
    subject, body_template = _lookup_copy(event, language)
    try:
        body = body_template.format(**payload)
    except KeyError:
        body = body_template

    rows: list[NotificationLog] = []
    channels = _channels_for_user(recipient_user)
    for channel in channels:
        recipient = ''
        if channel == 'email':
            recipient = recipient_email or (recipient_user.email if recipient_user else '')
        elif channel in ('sms', 'whatsapp'):
            recipient = recipient_phone
        elif channel == 'inapp':
            recipient = recipient_user.username if recipient_user else 'system'
        if not recipient:
            row = NotificationLog.objects.create(
                event=event, channel=channel, recipient='-',
                user=recipient_user, subject=subject, body=body,
                payload=payload, status='skipped',
                error='No recipient address for this channel.',
            )
            rows.append(row)
            continue
        if channel == 'inapp':
            row = NotificationLog.objects.create(
                event=event, channel=channel, recipient=recipient,
                user=recipient_user, subject=subject, body=body,
                payload=payload, status='sent',
                sent_at=timezone.now(),
            )
            rows.append(row)
            continue
        provider = _provider_for(channel)
        if provider is None:
            rows.append(NotificationLog.objects.create(
                event=event, channel=channel, recipient=recipient,
                user=recipient_user, subject=subject, body=body,
                payload=payload, status='skipped',
                error='No provider available.',
            ))
            continue
        result = provider.send(recipient=recipient, subject=subject, body=body, payload=payload)
        rows.append(NotificationLog.objects.create(
            event=event, channel=channel, recipient=recipient,
            user=recipient_user, subject=subject, body=body,
            payload=payload, status='sent' if result.ok else 'failed',
            sent_at=timezone.now() if result.ok else None,
            error='' if result.ok else result.detail,
        ))
    return rows


# ── Event subscribers ────────────────────────────────────────────────


def _customer_payload(order: CustomerOrder, **extra) -> dict:
    return {
        'name': order.customer.first_name,
        'order_id': order.pk,
        'currency': order.currency.code if order.currency else 'EUR',
        'amount': str(order.final_amount),
        **extra,
    }


@events.on(events.ORDER_READY)
def _on_ready(event_name, target, actor, payload):
    if not isinstance(target, CustomerOrder):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload=_customer_payload(target))


@events.on(events.ORDER_DELIVERED)
def _on_delivered(event_name, target, actor, payload):
    if not isinstance(target, CustomerOrder):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload=_customer_payload(target))


@events.on(events.PAYMENT_RECEIVED)
def _on_payment(event_name, target, actor, payload):
    if isinstance(target, Payment):
        order = target.order
        amount = str(target.amount)
    elif isinstance(target, CustomerOrder):
        order = target
        amount = payload.get('amount', str(order.final_amount))
    else:
        return
    customer = order.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload={**_customer_payload(order), 'amount': amount})


@events.on(events.PAYMENT_REMINDER)
def _on_payment_reminder(event_name, target, actor, payload):
    if not isinstance(target, CustomerOrder):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload=_customer_payload(target))


@events.on(events.PICKUP_REMINDER)
def _on_pickup(event_name, target, actor, payload):
    if not isinstance(target, CustomerOrder):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload=_customer_payload(target))


@events.on(events.MATERIAL_LOW)
def _on_low(event_name, target, actor, payload):
    if not isinstance(target, Material):
        return
    from django.contrib.auth.models import User
    for staff_user in User.objects.filter(is_staff=True):
        notify(event=event_name, recipient_user=staff_user,
               recipient_email=staff_user.email,
               language='es',
               payload={'material': target.name,
                        'stock': payload.get('stock_on_hand', '0')})


@events.on(events.MATERIAL_APPROVED)
@events.on(events.MATERIAL_REJECTED)
def _on_request_decision(event_name, target, actor, payload):
    if not isinstance(target, MaterialRequest):
        return
    requester_user = getattr(target.requested_by, 'user', None)
    notify(event=event_name, recipient_user=requester_user,
           recipient_email=target.requested_by.email,
           language='es',
           payload={'material': target.material.name})


@events.on(events.LEAD_RECEIVED)
def _on_lead(event_name, target, actor, payload):
    from django.contrib.auth.models import User
    for staff_user in User.objects.filter(is_staff=True):
        notify(event=event_name, recipient_user=staff_user,
               recipient_email=staff_user.email, language='es',
               payload={})


@events.on(events.APPOINTMENT_REQUESTED)
def _on_appointment_request(event_name, target, actor, payload):
    if not isinstance(target, Appointment):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload={'kind': target.get_kind_display()})


@events.on(events.FITTING_REMINDER)
def _on_fitting(event_name, target, actor, payload):
    if not isinstance(target, Appointment):
        return
    customer = target.customer
    notify(event=event_name,
           recipient_user=customer.user, recipient_email=customer.email,
           recipient_phone=customer.phone, language=customer.language,
           payload={
               'name': customer.first_name,
               'when': target.scheduled_at.strftime('%Y-%m-%d %H:%M'),
               'place': target.location,
           })
    target.reminder_sent_at = timezone.now()
    target.save(update_fields=['reminder_sent_at'])
