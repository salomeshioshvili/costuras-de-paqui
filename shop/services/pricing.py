"""Single source of pricing truth.

`quote_order(...)` reads the live pricing tables, computes line totals,
and returns an immutable JSON snapshot to freeze on the order at booking
time. Existing OrderItem.calculate_auto_unit_price stays as a fallback
for items created without going through this service.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.utils import timezone

from shop.models import (
    AddOn, CustomerOrder, DiscountRule, FabricType, GarmentCategory,
    ReferralCode, UrgencySurcharge,
)
from shop.services import fx


def _decimal(value, default=Decimal('0.00')) -> Decimal:
    if value is None or value == '':
        return default
    return Decimal(str(value))


def _category_for(garment_text: str) -> GarmentCategory | None:
    text = (garment_text or '').lower()
    categories = sorted(
        GarmentCategory.objects.filter(is_active=True),
        key=lambda c: len(c.name),
        reverse=True,
    )
    for cat in categories:
        if cat.name.lower() in text:
            return cat
    return None


def _fabric_for(fabric_text: str) -> FabricType | None:
    text = (fabric_text or '').lower()
    fabrics = sorted(
        FabricType.objects.filter(is_active=True),
        key=lambda f: len(f.name),
        reverse=True,
    )
    for fabric_obj in fabrics:
        if fabric_obj.name.lower() in text:
            return fabric_obj
    return None


def _urgency_for(priority: str) -> UrgencySurcharge | None:
    return UrgencySurcharge.objects.filter(priority=priority, is_active=True).first()


def quote_item(*, garment_type, fabric='', priority='normal', quantity=1, addons: Iterable[str] = ()):
    """Return (unit_price, snapshot_dict) for one garment item.

    Fabric and urgency multipliers adjust the category base independently
    (additive deltas), never multiplied together on an inflated subtotal.
    """
    quantity = max(int(quantity or 1), 1)
    category = _category_for(garment_type)
    base = category.base_price if category else _legacy_fallback(garment_type)
    fabric_obj = _fabric_for(fabric)
    fabric_mult = fabric_obj.multiplier if fabric_obj else Decimal('1.00')
    urgency_obj = _urgency_for(priority)
    urgency_mult = urgency_obj.multiplier if urgency_obj else Decimal('1.00')

    fabric_delta = base * (fabric_mult - Decimal('1'))
    urgency_delta = base * (urgency_mult - Decimal('1'))
    unit_core = (base + fabric_delta + urgency_delta).quantize(Decimal('0.01'))

    addon_total = Decimal('0.00')
    addon_rows = []
    for name in addons or ():
        addon = AddOn.objects.filter(name__iexact=name, is_active=True).first()
        if not addon:
            continue
        if addon.kind == 'per_unit':
            amount = (addon.price * quantity).quantize(Decimal('0.01'))
        else:
            amount = addon.price
        addon_total += amount
        addon_rows.append({
            'name': addon.name, 'kind': addon.kind, 'price': str(addon.price),
            'applied_amount': str(amount),
        })

    unit_with_addons = unit_core + (addon_total / quantity if quantity else 0)
    snapshot = {
        'garment_type': garment_type,
        'fabric': fabric,
        'priority': priority,
        'quantity': quantity,
        'pricing_model': 'additive_base_adjustments',
        'category': {'name': category.name, 'base_price': str(base)} if category else None,
        'fabric_type': {'name': fabric_obj.name, 'multiplier': str(fabric_mult)} if fabric_obj else None,
        'fabric_delta_to_base': str(fabric_delta.quantize(Decimal('0.01'))),
        'urgency': {'priority': priority, 'multiplier': str(urgency_mult)} if urgency_obj else None,
        'urgency_delta_to_base': str(urgency_delta.quantize(Decimal('0.01'))),
        'addons': addon_rows,
        'unit_core': str(unit_core),
        'unit_price': str(unit_core),
        'unit_with_addons': str(unit_with_addons.quantize(Decimal('0.01'))),
    }
    return unit_with_addons.quantize(Decimal('0.01')), snapshot


def _legacy_fallback(garment_type: str) -> Decimal:
    """Fallback to the legacy keyword pricing if no matching category exists."""
    from shop.models import OrderItem as OI
    placeholder = OI(garment_type=garment_type)
    return placeholder.calculate_auto_unit_price()


def apply_discount(*, customer, code: str, subtotal: Decimal):
    """Return (discount_amount, snapshot_dict|None)."""
    if not code:
        return Decimal('0.00'), None
    code_norm = code.strip()
    rule = DiscountRule.objects.filter(code__iexact=code_norm).first()
    if rule and rule.is_applicable(customer):
        if rule.kind == 'percentage':
            amount = (subtotal * rule.value / Decimal('100')).quantize(Decimal('0.01'))
        else:
            amount = min(rule.value, subtotal)
        return amount, {
            'code': rule.code, 'kind': rule.kind, 'value': str(rule.value),
            'applied_amount': str(amount), 'rule': 'discount_rule',
        }
    referral = ReferralCode.objects.filter(code__iexact=code_norm).first()
    if referral and referral.can_be_used():
        amount = (subtotal * referral.percent / Decimal('100')).quantize(Decimal('0.01'))
        return amount, {
            'code': referral.code, 'kind': 'percentage', 'value': str(referral.percent),
            'applied_amount': str(amount), 'rule': 'referral_code',
            'referrer_id': referral.customer_id,
        }
    return Decimal('0.00'), None


def quote_order(*, customer, items: list[dict], code: str = '', currency_code: str = 'EUR'):
    """items = [{'garment_type','fabric','priority','quantity','addons':[]},...]

    Returns dict with line totals, subtotal, discount, total, snapshot,
    currency, exchange_rate, base_subtotal, base_total, applied_code.
    """
    line_rows = []
    subtotal = Decimal('0.00')
    for raw in items:
        unit_price, item_snap = quote_item(
            garment_type=raw.get('garment_type', ''),
            fabric=raw.get('fabric', ''),
            priority=raw.get('priority', 'normal'),
            quantity=raw.get('quantity', 1),
            addons=raw.get('addons') or (),
        )
        qty = int(raw.get('quantity', 1) or 1)
        line_total = (unit_price * qty).quantize(Decimal('0.01'))
        item_snap['line_total'] = str(line_total)
        line_rows.append({**raw, 'unit_price': str(unit_price),
                          'line_total': str(line_total),
                          'snapshot': item_snap})
        subtotal += line_total

    discount, discount_snap = apply_discount(
        customer=customer, code=code, subtotal=subtotal,
    )
    final = (subtotal - discount).quantize(Decimal('0.01'))

    rate = fx.latest_rate(currency_code)
    base_currency = fx.base_currency()
    base_code = base_currency.code if base_currency else 'EUR'
    if currency_code == base_code:
        base_subtotal = subtotal
        base_final = final
    else:
        base_subtotal = (subtotal / rate).quantize(Decimal('0.01')) if rate else subtotal
        base_final = (final / rate).quantize(Decimal('0.01')) if rate else final

    snapshot = {
        'created_at': timezone.now().isoformat(),
        'currency': currency_code,
        'exchange_rate_to_base': str(rate),
        'lines': line_rows,
        'subtotal': str(subtotal),
        'discount': str(discount),
        'discount_rule': discount_snap,
        'final': str(final),
        'base_currency': base_code,
        'base_subtotal': str(base_subtotal),
        'base_final': str(base_final),
        'applied_code': code or '',
    }
    return {
        'subtotal': subtotal, 'discount': discount, 'final': final,
        'lines': line_rows, 'snapshot': snapshot,
        'exchange_rate': rate,
        'base_subtotal': base_subtotal, 'base_final': base_final,
        'applied_code': code or '',
    }


def freeze_onto_order(order: CustomerOrder, quote: dict, *, currency_code: str = 'EUR') -> CustomerOrder:
    """Persist the quote onto the order. Idempotent."""
    from shop.models import Currency
    currency = Currency.objects.filter(code=currency_code).first()
    order.subtotal_amount = quote['subtotal']
    order.final_amount = quote['final']
    order.base_subtotal = quote['base_subtotal']
    order.base_final = quote['base_final']
    order.exchange_rate = quote['exchange_rate']
    order.currency = currency
    order.applied_discount_code = quote.get('applied_code') or ''
    order.pricing_snapshot = quote['snapshot']
    discount_amt = quote.get('discount') or Decimal('0.00')
    if discount_amt > 0:
        order.order_discount_type = 'fixed'
        order.order_discount_value = discount_amt
    else:
        order.order_discount_type = 'none'
        order.order_discount_value = Decimal('0.00')
    order.save(update_fields=[
        'subtotal_amount', 'final_amount', 'base_subtotal', 'base_final',
        'exchange_rate', 'currency', 'applied_discount_code', 'pricing_snapshot',
        'order_discount_type', 'order_discount_value', 'updated_at',
    ])
    return order
