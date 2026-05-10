"""Email provider. Console default; switches to SMTP when SMTP_HOST is set."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from .base import NotificationProvider, SendResult

log = logging.getLogger('shop.email')


class ConsoleEmailProvider(NotificationProvider):
    name = 'console-email'

    def send(self, *, recipient, subject, body, payload=None):
        log.info('[email→%s] %s\n%s', recipient, subject, body)
        return SendResult(ok=True, detail='logged-to-console')


class SmtpEmailProvider(NotificationProvider):
    name = 'smtp-email'

    def send(self, *, recipient, subject, body, payload=None):
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@costurasdepaqui.es'),
                recipient_list=[recipient],
                fail_silently=False,
            )
            return SendResult(ok=True, detail='smtp-ok')
        except Exception as exc:
            log.exception('SMTP send failed: %s', exc)
            return SendResult(ok=False, detail=str(exc))


def get_provider() -> NotificationProvider:
    if getattr(settings, 'SMTP_HOST', '') and getattr(settings, 'EMAIL_BACKEND', '').endswith('SMTP'):
        return SmtpEmailProvider()
    return ConsoleEmailProvider()
