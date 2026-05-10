"""FX conversion service.

Live rates are read from the ExchangeRate table. New rates are appended
by `python manage.py refresh_rates`. Historical orders never call this:
they read their frozen `exchange_rate` field instead.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import date

from django.utils import timezone

from shop.models import Currency, ExchangeRate
from shop.providers import fx as fx_provider


def base_currency() -> Currency | None:
    return Currency.objects.filter(is_base=True).first() or Currency.objects.filter(code='EUR').first()


def latest_rate(code: str, on: date | None = None) -> Decimal:
    """Return how many of `code` equal 1 unit of base. EUR returns 1."""
    base = base_currency()
    if base and base.code == code:
        return Decimal('1.000000')
    qs = ExchangeRate.objects.filter(currency__code=code)
    if on is not None:
        qs = qs.filter(captured_on__lte=on)
    rate = qs.order_by('-captured_on').first()
    if rate:
        return rate.rate_to_base
    rates = fx_provider.fetch_rates_eur_base()
    return rates.get(code, Decimal('1.000000'))


def to_base(amount: Decimal, code: str, on: date | None = None) -> Decimal:
    """Convert `amount` in `code` into the base currency."""
    if amount is None:
        return Decimal('0.00')
    rate = latest_rate(code, on=on)
    if rate == 0:
        return Decimal('0.00')
    return (Decimal(amount) / rate).quantize(Decimal('0.01'))


def from_base(amount: Decimal, code: str, on: date | None = None) -> Decimal:
    if amount is None:
        return Decimal('0.00')
    rate = latest_rate(code, on=on)
    return (Decimal(amount) * rate).quantize(Decimal('0.01'))


def convert(amount: Decimal, src: str, dst: str, on: date | None = None) -> Decimal:
    if src == dst:
        return Decimal(amount).quantize(Decimal('0.01'))
    base_amount = to_base(amount, src, on=on)
    return from_base(base_amount, dst, on=on)


def refresh_all_rates(*, source: str = 'provider') -> int:
    rates = fx_provider.fetch_rates_eur_base()
    today = timezone.now().date()
    written = 0
    for code, rate in rates.items():
        currency = Currency.objects.filter(code=code).first()
        if currency is None:
            continue
        ExchangeRate.objects.update_or_create(
            currency=currency, captured_on=today,
            defaults={'rate_to_base': rate, 'source': source},
        )
        written += 1
    return written
