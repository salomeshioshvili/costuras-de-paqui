"""Lead intake → Customer + Order conversion."""
from __future__ import annotations

import secrets
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction

from shop import events
from shop.models import Customer, CustomerOrder, Lead, OrderItem
from shop.services import audit
from shop.services import pricing as pricing_service


@transaction.atomic
def convert_lead(lead: Lead, *, actor=None, password: str | None = None) -> CustomerOrder:
    customer = lead.converted_customer
    if customer is None and lead.email:
        customer = Customer.objects.filter(email__iexact=lead.email).first()
    if customer is None:
        user = None
        if lead.email:
            user, created = User.objects.get_or_create(
                username=lead.email,
                defaults={'email': lead.email, 'first_name': lead.name.split(' ')[0],
                          'last_name': ' '.join(lead.name.split(' ')[1:])},
            )
            if created:
                user.set_password(password or secrets.token_urlsafe(8))
                user.save()
        customer = Customer.objects.create(
            first_name=lead.name.split(' ')[0],
            last_name=' '.join(lead.name.split(' ')[1:]),
            email=lead.email,
            phone=lead.phone,
            language=lead.language,
            user=user,
        )

    order = CustomerOrder.objects.create(
        customer=customer,
        due_date=lead.due_date,
        priority='normal',
        status='received',
        payment_status='unpaid',
        notes=lead.notes,
        customer_notes=lead.notes,
        created_by=actor if actor and actor.is_authenticated else None,
    )
    item = OrderItem.objects.create(
        order=order,
        garment_type=lead.garment_type,
        fabric=lead.fabric,
        color=lead.color,
        special_instructions=lead.notes,
        quantity=1,
    )
    quote = pricing_service.quote_order(
        customer=customer,
        items=[{
            'garment_type': lead.garment_type,
            'fabric': lead.fabric,
            'priority': 'normal',
            'quantity': 1,
        }],
    )
    pricing_service.freeze_onto_order(order, quote)
    item.unit_price = Decimal(quote['lines'][0]['unit_price'])
    item.save(update_fields=['unit_price'])

    lead.status = 'converted'
    lead.converted_customer = customer
    lead.converted_order = order
    lead.save(update_fields=['status', 'converted_customer', 'converted_order'])

    audit.log(
        actor=actor, action='lead.converted', target=lead,
        before={'status': 'new'}, after={'order_id': order.pk, 'customer_id': customer.pk},
        message=f'Converted lead → order #{order.pk}',
    )
    events.emit(events.LEAD_CONVERTED, target=lead, actor=actor, payload={
        'order_id': order.pk, 'customer_id': customer.pk,
    })
    return order
