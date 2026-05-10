"""Server-side rules for customer booking due dates."""
from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone


def earliest_allowed_booking_date() -> date:
    days = int(getattr(settings, 'BOOKING_MIN_DAYS_AHEAD', 1))
    return timezone.localdate() + timedelta(days=days)


def is_due_date_allowed_booking(due: date) -> bool:
    return due >= earliest_allowed_booking_date()
