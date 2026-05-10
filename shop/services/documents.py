"""Receipt/invoice rendering helpers."""
from __future__ import annotations

from django.template.loader import render_to_string
from django.utils import translation

from shop.models import CustomerOrder, Invoice, Payment, Receipt
from shop.services import display_currency as display_currency_service


def ensure_invoice(order: CustomerOrder) -> Invoice:
    inv, _ = Invoice.objects.get_or_create(
        order=order,
        defaults={
            'language': order.customer.language if order.customer else 'es',
            'total': order.final_amount,
            'currency_code': order.currency.code if order.currency else 'EUR',
        },
    )
    return inv


def ensure_receipt(payment: Payment) -> Receipt:
    rec, _ = Receipt.objects.get_or_create(
        payment=payment,
        defaults={
            'language': payment.order.customer.language if payment.order.customer else 'es',
            'amount': payment.amount,
            'currency_code': payment.order.currency.code if payment.order.currency else 'EUR',
        },
    )
    return rec


def render_invoice_html(order: CustomerOrder, *, language: str | None = None) -> str:
    lang = language or (order.customer.language if order.customer else 'es')
    inv = ensure_invoice(order)
    currency_code = order.currency.code if order.currency else 'EUR'
    currency_symbol = order.currency.symbol if order.currency else '€'
    with translation.override(lang):
        return render_to_string('print/invoice.html', {
            'order': order,
            'invoice': inv,
            'language': lang,
            'snapshot': order.pricing_snapshot or {},
            'currency_code': currency_code,
            'currency_symbol': currency_symbol,
        })


def render_receipt_html(
    payment: Payment,
    *,
    language: str | None = None,
    display_currency_code: str | None = None,
) -> str:
    lang = language or (payment.order.customer.language if payment.order.customer else 'es')
    rec = ensure_receipt(payment)
    order = payment.order
    booking_code = display_currency_service.booking_currency_code(order)
    display_code = (display_currency_code or booking_code or 'EUR').upper()
    show_display = display_code != booking_code
    display_amt = None
    display_fmt = ''
    if show_display:
        display_amt = display_currency_service.convert_booking_amount_for_display(
            order, payment.amount, display_code,
        )
        display_fmt = display_currency_service.format_money_amount(display_amt, display_code)
    ctx = {
        'payment': payment,
        'order': order,
        'receipt': rec,
        'language': lang,
        'currency_code': booking_code,
        'display_currency_code': display_code if show_display else None,
        'display_payment_amount': display_amt,
        'display_payment_formatted': display_fmt,
    }
    with translation.override(lang):
        return render_to_string('print/receipt.html', ctx)
