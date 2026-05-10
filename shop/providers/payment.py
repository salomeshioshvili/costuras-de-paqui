"""Payment provider. Stub default returns a confirmation page; Stripe when keys exist."""
from __future__ import annotations

import logging

from django.conf import settings
from django.urls import reverse

from .base import PaymentProvider

log = logging.getLogger('shop.payment')


class StubPaymentProvider(PaymentProvider):
    name = 'stub'

    def start_checkout(self, *, order, success_url: str, cancel_url: str) -> dict:
        # Always send the customer to the in-app confirmation page.
        return {
            'mode': 'inline',
            'url': reverse('portal_pay_order', kwargs={'pk': order.pk}),
            'provider': self.name,
        }

    def handle_webhook(self, *, request) -> dict:
        return {'handled': False, 'reason': 'stub-no-webhook'}


class StripePaymentProvider(PaymentProvider):
    name = 'stripe'

    def __init__(self):
        import stripe  # noqa: lazy optional dependency
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self.stripe = stripe

    def start_checkout(self, *, order, success_url: str, cancel_url: str) -> dict:
        try:
            session = self.stripe.checkout.Session.create(
                mode='payment',
                line_items=[{
                    'price_data': {
                        'currency': (order.currency.code if order.currency else 'eur').lower(),
                        'product_data': {'name': f'Order #{order.pk} — Costuras de Paqui'},
                        'unit_amount': int(order.final_amount * 100),
                    },
                    'quantity': 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={'order_id': str(order.pk)},
            )
            return {'mode': 'redirect', 'url': session.url, 'provider': self.name}
        except Exception as exc:
            log.exception('Stripe session failed: %s', exc)
            return {'mode': 'inline',
                    'url': reverse('portal_pay_order', kwargs={'pk': order.pk}),
                    'provider': 'stub-fallback'}

    def handle_webhook(self, *, request) -> dict:
        try:
            payload = request.body
            sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
            event = self.stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
            )
            if event['type'] == 'checkout.session.completed':
                order_id = event['data']['object']['metadata']['order_id']
                return {'handled': True, 'order_id': int(order_id),
                        'amount': event['data']['object'].get('amount_total', 0) / 100}
            return {'handled': True, 'noop': True}
        except Exception as exc:
            log.exception('Stripe webhook error: %s', exc)
            return {'handled': False, 'error': str(exc)}


def get_provider() -> PaymentProvider:
    if getattr(settings, 'STRIPE_SECRET_KEY', ''):
        try:
            return StripePaymentProvider()
        except Exception as exc:
            log.warning('Stripe not available, falling back to stub: %s', exc)
    return StubPaymentProvider()
