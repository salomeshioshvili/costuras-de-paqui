"""Display-only currency conversion using live FX; booking amounts stay frozen."""
from __future__ import annotations

from decimal import Decimal

from shop.services import fx

SESSION_KEY_DISPLAY_CURRENCY = 'display_currency_code'

_CURRENCY_SYMBOLS = {
    'EUR': '€', 'USD': '$', 'GBP': '£', 'BRL': 'R$', 'CHF': 'CHF ', 'JPY': '¥',
}


def booking_currency_code(order) -> str:
    cur = getattr(order, 'currency', None)
    if cur and getattr(cur, 'code', None):
        return cur.code
    base = fx.base_currency()
    return base.code if base else 'EUR'


def convert_booking_amount_for_display(
    order, amount: Decimal | str | float | None, display_code: str,
) -> Decimal:
    if amount is None:
        return Decimal('0.00')
    book_code = booking_currency_code(order)
    display = (display_code or book_code or 'EUR').upper()
    amt = Decimal(str(amount))
    if display == book_code:
        return amt.quantize(Decimal('0.01'))
    return fx.convert(amt, book_code, display)


def format_money_amount(amount: Decimal, currency_code: str) -> str:
    code = (currency_code or 'EUR').upper()
    try:
        quant = Decimal(amount).quantize(Decimal('0.01'))
    except Exception:
        return str(amount)
    symbol = _CURRENCY_SYMBOLS.get(code, '')
    if symbol:
        return f'{symbol}{quant:,.2f}'
    return f'{quant:,.2f} {code}'


def resolve_display_currency_code(request) -> str:
    session_code = request.session.get(SESSION_KEY_DISPLAY_CURRENCY)
    if session_code:
        return str(session_code).upper()[:3]
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        from shop.models import Customer

        customer = Customer.objects.filter(user=user).select_related('preferred_currency').first()
        if customer and customer.preferred_currency_id:
            return customer.preferred_currency.code
    base = fx.base_currency()
    return base.code if base else 'EUR'
