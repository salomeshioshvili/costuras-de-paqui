"""Custom template tags: next_states, money formatting, qr."""
from __future__ import annotations

from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

from shop import workflow as workflow_engine
from shop.services import display_currency as display_currency_service
from shop.services import qr as qr_service

register = template.Library()


@register.simple_tag
def next_states(obj):
    """Return [(value, label, blocking_reason_or_none), ...] for the obj."""
    return workflow_engine.next_states(obj)


@register.simple_tag
def blocking_reason(obj, target):
    return workflow_engine.blocking_reason(obj, target)


@register.filter
def money(value, currency_code='EUR'):
    """Pretty-print an amount with its currency symbol."""
    if value is None:
        return ''
    try:
        amount = Decimal(value).quantize(Decimal('0.01'))
    except Exception:
        return value
    symbol = {'EUR': '€', 'USD': '$', 'GBP': '£', 'BRL': 'R$', 'CHF': 'CHF '}.get(
        (currency_code or 'EUR').upper(), ''
    )
    return f'{symbol}{amount:,.2f}' if symbol else f'{amount:,.2f} {currency_code}'


@register.simple_tag
def order_money(order, attr='final_amount'):
    value = getattr(order, attr, None)
    code = order.currency.code if getattr(order, 'currency', None) else 'EUR'
    return money(value, code)


@register.simple_tag(takes_context=True)
def order_money_display(context, order, amount):
    display_code = context.get('display_currency_code') or 'EUR'
    converted = display_currency_service.convert_booking_amount_for_display(
        order, amount, display_code,
    )
    return display_currency_service.format_money_amount(converted, display_code)


@register.simple_tag
def qr_image(payload, alt='QR'):
    url = qr_service.qr_png_data_url(payload)
    return mark_safe(f'<img src="{url}" alt="{alt}" class="qr-img" />')


@register.filter
def get_item(d, key):
    """{{ mydict|get_item:key }} — safe dict lookup in templates."""
    if hasattr(d, 'get'):
        return d.get(key, '')
    return ''
