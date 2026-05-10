"""SMS provider. Console default; Twilio when TWILIO_* keys are present."""
from __future__ import annotations

import logging

from django.conf import settings

from .base import NotificationProvider, SendResult

log = logging.getLogger('shop.sms')


class ConsoleSmsProvider(NotificationProvider):
    name = 'console-sms'

    def send(self, *, recipient, subject, body, payload=None):
        log.info('[sms→%s] %s', recipient, body[:140])
        return SendResult(ok=True, detail='logged-to-console')


class TwilioSmsProvider(NotificationProvider):
    name = 'twilio-sms'

    def __init__(self):
        from twilio.rest import Client  # noqa: imported lazily if SMS enabled
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    def send(self, *, recipient, subject, body, payload=None):
        try:
            self.client.messages.create(
                to=recipient,
                from_=settings.TWILIO_FROM_NUMBER,
                body=body[:1600],
            )
            return SendResult(ok=True, detail='twilio-ok')
        except Exception as exc:
            log.exception('Twilio SMS failed: %s', exc)
            return SendResult(ok=False, detail=str(exc))


def get_provider() -> NotificationProvider:
    if getattr(settings, 'TWILIO_ACCOUNT_SID', '') and getattr(settings, 'TWILIO_AUTH_TOKEN', ''):
        try:
            return TwilioSmsProvider()
        except Exception as exc:
            log.warning('Twilio not available, falling back to console: %s', exc)
    return ConsoleSmsProvider()
