"""Billing / payment service. Real money goes through providers."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from shop import events
from shop.models import CustomerOrder, Payment, Receipt
from shop.providers import payment as payment_provider
from shop.services import audit


def remaining_balance(order: CustomerOrder) -> Decimal:
    paid = order.payments.aggregate_total = order.payments.values_list('amount', flat=True)
    paid_total = sum((Decimal(str(a)) for a in paid), Decimal('0.00'))
    return (Decimal(order.final_amount) - paid_total).quantize(Decimal('0.01'))


def start_checkout(*, order, success_url: str, cancel_url: str) -> dict:
    provider = payment_provider.get_provider()
    return provider.start_checkout(order=order, success_url=success_url, cancel_url=cancel_url)


@transaction.atomic
def record_payment(*, order, amount, method='card', stage='partial',
                   reference='', actor=None, channel='manual') -> Payment:
    payment = Payment.objects.create(
        order=order, amount=amount, payment_method=method,
        payment_stage=stage, reference_code=reference,
        recorded_by=actor if actor and actor.is_authenticated else None,
        notes=f'Channel: {channel}',
    )
    Receipt.objects.create(
        payment=payment,
        amount=amount,
        currency_code=order.currency.code if order.currency else 'EUR',
        language=order.customer.language if order.customer else 'es',
    )
    paid = order.payments.aggregate_total = sum(
        (Decimal(str(p.amount)) for p in order.payments.all()), Decimal('0.00')
    )
    before_status = order.payment_status
    if paid >= Decimal(order.final_amount):
        order.payment_status = 'paid'
    elif paid > 0:
        order.payment_status = 'partially_paid'
    if order.payment_status != before_status:
        order.save(update_fields=['payment_status'])
        audit.log(
            actor=actor, action='order.payment_status', target=order,
            before={'payment_status': before_status},
            after={'payment_status': order.payment_status},
            message=f'Payment {amount} via {method}',
        )
    audit.log(
        actor=actor, action='payment.recorded', target=payment,
        before={}, after={'amount': str(amount), 'method': method},
        message=f'Payment for order #{order.pk}',
    )
    events.emit(events.PAYMENT_RECEIVED, target=payment, actor=actor, payload={
        'amount': str(amount), 'method': method, 'order_id': order.pk,
    })
    return payment
