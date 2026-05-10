"""Provider protocol used by all channel adapters."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    detail: str = ''


class NotificationProvider:
    name: str = 'base'

    def send(self, *, recipient: str, subject: str, body: str, payload: dict | None = None) -> SendResult:
        raise NotImplementedError


class PaymentProvider:
    name: str = 'base'

    def start_checkout(self, *, order, success_url: str, cancel_url: str) -> dict:
        """Return {'mode': 'redirect'|'inline', 'url': str}."""
        raise NotImplementedError

    def handle_webhook(self, *, request) -> dict:
        return {'handled': False}
