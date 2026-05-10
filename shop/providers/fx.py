"""FX rate provider. Falls back to last DB row when no live source is set."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

log = logging.getLogger('shop.fx')


def fetch_rates_eur_base() -> dict[str, Decimal]:
    """Return {'USD': Decimal('1.08'), ...} expressing how much of *currency* equals 1 EUR.

    The provider is stub-by-default; if an EXCHANGE_RATE_API_URL is configured AND
    `requests` is importable, we hit it; otherwise we return a hand-rolled snapshot.
    """
    url = getattr(settings, 'EXCHANGE_RATE_API_URL', '')
    if url:
        try:
            import requests  # type: ignore
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            data = r.json()
            rates = data.get('rates') or {}
            return {code: Decimal(str(v)) for code, v in rates.items()}
        except Exception as exc:
            log.warning('FX fetch failed (%s) — using stub snapshot', exc)
    return {
        'EUR': Decimal('1.000000'),
        'USD': Decimal('1.080000'),
        'GBP': Decimal('0.860000'),
        'BRL': Decimal('5.300000'),
        'CHF': Decimal('0.960000'),
    }
