"""WhatsApp provider. Console default; Twilio WhatsApp when configured."""
from __future__ import annotations

import logging

from django.conf import settings

from .base import NotificationProvider, SendResult

log = logging.getLogger('shop.whatsapp')


class ConsoleWhatsAppProvider(NotificationProvider):
    name = 'console-whatsapp'

    def send(self, *, recipient, subject, body, payload=None):
        log.info('[whatsapp→%s] %s', recipient, body)
        return SendResult(ok=True, detail='logged-to-console')


class TwilioWhatsAppProvider(NotificationProvider):
    name = 'twilio-whatsapp'

    def __init__(self):
        from twilio.rest import Client  # noqa
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    def send(self, *, recipient, subject, body, payload=None):
        try:
            target = recipient if recipient.startswith('whatsapp:') else f'whatsapp:{recipient}'
            self.client.messages.create(
                to=target,
                from_=f'whatsapp:{settings.TWILIO_WHATSAPP_FROM}',
                body=body[:1600],
            )
            return SendResult(ok=True, detail='whatsapp-ok')
        except Exception as exc:
            log.exception('Twilio WhatsApp failed: %s', exc)
            return SendResult(ok=False, detail=str(exc))


def get_provider() -> NotificationProvider:
    if getattr(settings, 'TWILIO_WHATSAPP_FROM', '') and getattr(settings, 'TWILIO_ACCOUNT_SID', ''):
        try:
            return TwilioWhatsAppProvider()
        except Exception as exc:
            log.warning('Twilio WhatsApp not available, falling back to console: %s', exc)
    return ConsoleWhatsAppProvider()
