"""Inventory helpers: stock adjustments, supplier order generation."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from shop import events
from shop.models import (
    Material, MaterialRequest, SupplierOrder, SupplierOrderLine,
)
from shop.services import audit


def low_stock_materials():
    return [m for m in Material.objects.filter(is_active=True)
            if m.is_low_stock]


@transaction.atomic
def create_supplier_order_from_request(req: MaterialRequest, *, actor=None) -> SupplierOrder:
    if req.material.supplier is None:
        raise ValueError('Material has no supplier configured.')
    so = SupplierOrder.objects.create(
        supplier=req.material.supplier,
        status='draft',
        created_by=actor if actor and actor.is_authenticated else None,
    )
    SupplierOrderLine.objects.create(
        supplier_order=so,
        material=req.material,
        quantity=req.quantity,
        unit_cost=req.material.unit_cost,
    )
    so.recalculate_total()
    audit.log(
        actor=actor, action='supplier_order.created', target=so,
        before={}, after={'supplier_id': so.supplier_id, 'total': str(so.total)},
        message=f'Created from material request #{req.pk}',
    )
    return so


@transaction.atomic
def receive_supplier_order(so: SupplierOrder, *, actor=None) -> SupplierOrder:
    for line in so.lines.all():
        before = {'stock_on_hand': str(line.material.stock_on_hand)}
        line.material.stock_on_hand = (line.material.stock_on_hand or Decimal('0')) + line.quantity
        line.material.save(update_fields=['stock_on_hand'])
        line.received_quantity = line.quantity
        line.save(update_fields=['received_quantity'])
        audit.log(
            actor=actor, action='material.received', target=line.material,
            before=before, after={'stock_on_hand': str(line.material.stock_on_hand)},
            message=f'+{line.quantity} via SO #{so.pk}',
        )
    from shop.workflow import transition
    transition(so, to='received', actor=actor, comment='All lines received.')
    # Auto-fulfill source requests
    for req in so.source_requests.filter(status='converted'):
        from shop.workflow import transition_request
        transition_request(req, to='fulfilled', actor=actor, comment='Supplier order received.')
    events.emit(events.SUPPLIER_ORDER_RECEIVED, target=so, actor=actor, payload={})
    return so
