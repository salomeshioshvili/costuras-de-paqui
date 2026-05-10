"""Pricing snapshot + historical-read invariant tests."""
from decimal import Decimal

from django.test import TestCase

from shop.models import (
    AddOn, Currency, CustomerOrder, FabricType, GarmentCategory,
    Customer, ExchangeRate, OrderItem, UrgencySurcharge,
)
from shop.services import pricing


class PricingSnapshotTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        Currency.objects.create(code='USD', name='US Dollar', symbol='$')
        ExchangeRate.objects.create(
            currency=Currency.objects.get(code='USD'),
            rate_to_base=Decimal('1.10'),
        )
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('60'))
        FabricType.objects.create(name='Silk', multiplier=Decimal('1.50'))
        UrgencySurcharge.objects.create(priority='normal', multiplier=Decimal('1.00'))
        AddOn.objects.create(name='Lining', kind='flat', price=Decimal('12'))

        self.customer = Customer.objects.create(first_name='S', last_name='Snap')

    def test_quote_freezes_snapshot(self):
        quote = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': 'Silk',
                     'priority': 'normal', 'quantity': 1, 'addons': ['Lining']}],
        )
        self.assertEqual(quote['subtotal'], Decimal('102.00'))
        snap = quote['snapshot']
        self.assertEqual(snap['lines'][0]['snapshot']['fabric_type']['name'], 'Silk')
        self.assertEqual(snap['lines'][0]['snapshot']['addons'][0]['name'], 'Lining')

    def test_historical_reads_use_snapshot(self):
        order = CustomerOrder.objects.create(customer=self.customer, status='received')
        item = OrderItem.objects.create(order=order, garment_type='Dress',
                                          fabric='Silk', quantity=1)
        quote = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': 'Silk',
                     'priority': 'normal', 'quantity': 1}],
        )
        pricing.freeze_onto_order(order, quote)
        item.unit_price = Decimal(quote['lines'][0]['unit_price'])
        item.save(update_fields=['unit_price'])
        original_total = order.final_amount

        # Mutate every live pricing/FX table.
        GarmentCategory.objects.filter(name='Dress').update(base_price=Decimal('1000'))
        FabricType.objects.filter(name='Silk').update(multiplier=Decimal('5.00'))
        ExchangeRate.objects.filter(currency__code='USD').update(rate_to_base=Decimal('99'))

        order.refresh_from_db()
        # Snapshot fields are unchanged.
        self.assertEqual(order.final_amount, original_total)
        self.assertEqual(order.base_final, original_total)
        self.assertEqual(order.pricing_snapshot['final'], str(original_total))

    def test_referral_discount_lookup(self):
        from shop.models import ReferralCode
        referrer = Customer.objects.create(first_name='Ref', last_name='Errer',
                                             referral_code='CDP-TEST01')
        ReferralCode.objects.create(customer=referrer, code='CDP-TEST01',
                                      percent=Decimal('10'))
        amount, snap = pricing.apply_discount(
            customer=self.customer, code='CDP-TEST01', subtotal=Decimal('100'),
        )
        self.assertEqual(amount, Decimal('10.00'))
        self.assertEqual(snap['rule'], 'referral_code')
