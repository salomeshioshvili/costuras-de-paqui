"""FX conversion tests."""
from decimal import Decimal

from django.test import TestCase

from shop.models import Currency, ExchangeRate
from shop.services import fx


class FxTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        Currency.objects.create(code='USD', name='US Dollar', symbol='$')
        ExchangeRate.objects.create(
            currency=Currency.objects.get(code='USD'),
            rate_to_base=Decimal('1.10'),
        )

    def test_to_base(self):
        self.assertEqual(fx.to_base(Decimal('110.00'), 'USD'), Decimal('100.00'))

    def test_from_base(self):
        self.assertEqual(fx.from_base(Decimal('100.00'), 'USD'), Decimal('110.00'))

    def test_eur_is_identity(self):
        self.assertEqual(fx.latest_rate('EUR'), Decimal('1.000000'))
        self.assertEqual(fx.to_base(Decimal('50'), 'EUR'), Decimal('50.00'))
