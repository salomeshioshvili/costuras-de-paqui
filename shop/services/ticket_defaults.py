"""Default field values when creating a work ticket from order data."""
from __future__ import annotations

from shop.models import OrderItem, WorkTicket


def initial_fields_from_order_item(order_item: OrderItem) -> dict:
    order = order_item.order
    garment_bits = [f'Garment: {order_item.garment_type}']
    if order_item.fabric:
        garment_bits.append(f'Fabric: {order_item.fabric}')
    if order_item.color:
        garment_bits.append(f'Color: {order_item.color}')
    if order_item.size_label:
        garment_bits.append(f'Size: {order_item.size_label}')
    garment_line = ' · '.join(garment_bits)
    design_parts = [
        p for p in (
            order.customer_notes,
            order_item.special_instructions,
            order_item.description,
        ) if p and str(p).strip()
    ]
    design_notes = '\n\n'.join(design_parts)
    obs_parts = [p for p in (order.notes,) if p and str(p).strip()]
    observations = '\n\n'.join(obs_parts)
    currency_note = ''
    if order.currency_id:
        currency_note = (
            f'Order currency: {order.currency.code} '
            f'(rate {order.exchange_rate} to base at booking).'
        )
    elif order.exchange_rate and order.exchange_rate != 1:
        currency_note = f'Exchange rate at booking: {order.exchange_rate} to base.'
    extra_obs = []
    if currency_note:
        extra_obs.append(currency_note)
    if observations:
        extra_obs.insert(0, observations)
    observations_full = '\n\n'.join(extra_obs)
    measurements = order_item.measurements.all()
    meas_lines = [
        f'{m.measurement_type}: {m.measurement_value} {m.unit}'
        for m in measurements
    ]
    if meas_lines:
        block = 'Measurements:\n' + '\n'.join(meas_lines)
        design_notes = f'{design_notes}\n\n{block}'.strip() if design_notes else block
    if design_notes:
        design_notes = f'{garment_line}\n\n{design_notes}'
    else:
        design_notes = garment_line
    return {
        'priority': order.priority,
        'deadline': order.due_date,
        'design_notes': design_notes,
        'observations': observations_full,
    }


def augment_post_with_defaults(post_data, order_item: OrderItem | None) -> object:
    """Fill blank ticket fields from the order item before form validation."""
    if not order_item:
        return post_data
    defs = initial_fields_from_order_item(order_item)
    if not (post_data.get('design_notes') or '').strip():
        post_data['design_notes'] = defs.get('design_notes', '')
    if not (post_data.get('observations') or '').strip():
        post_data['observations'] = defs.get('observations', '')
    deadline_raw = post_data.get('deadline')
    if (not deadline_raw or not str(deadline_raw).strip()) and defs.get('deadline'):
        post_data['deadline'] = defs['deadline'].isoformat()
    return post_data


def merge_saved_ticket_if_blank(ticket: WorkTicket, defaults: dict) -> None:
    """After commit=False save, ensure persisted rows are not empty when order had data."""
    if not (ticket.design_notes or '').strip():
        ticket.design_notes = (defaults.get('design_notes') or '').strip()
    if not (ticket.observations or '').strip():
        ticket.observations = (defaults.get('observations') or '').strip()
    if ticket.deadline is None and defaults.get('deadline'):
        ticket.deadline = defaults['deadline']
