"""Targeted tests for pricing rules, booking dates, discounts, tickets, i18n."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from shop.models import (
    Currency, Customer, CustomerOrder, ExchangeRate, FabricType,
    GarmentCategory, Measurement, OrderItem, Payment, ReferralCode, UrgencySurcharge,
)
from shop.services import display_currency as display_currency_service
from shop.services import pricing
from shop.services import ticket_defaults as ticket_defaults_service


class PricingAdditiveModelTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('100'))
        FabricType.objects.create(name='Silk', multiplier=Decimal('2.00'))
        UrgencySurcharge.objects.create(priority='urgent', multiplier=Decimal('1.50'))
        UrgencySurcharge.objects.create(priority='normal', multiplier=Decimal('1.00'))
        self.customer = Customer.objects.create(first_name='T', last_name='P')

    def test_fabric_and_urgency_do_not_compound(self):
        unit, snap = pricing.quote_item(
            garment_type='Dress',
            fabric='Silk',
            priority='urgent',
            quantity=1,
        )
        compounded = Decimal('100') * Decimal('2') * Decimal('1.5')
        additive = Decimal('100') + Decimal('100') * (Decimal('2') - 1) + Decimal('100') * (
            Decimal('1.5') - 1
        )
        self.assertEqual(unit, additive.quantize(Decimal('0.01')))
        self.assertNotEqual(unit, compounded.quantize(Decimal('0.01')))
        self.assertEqual(snap.get('pricing_model'), 'additive_base_adjustments')

    def test_invalid_discount_code_returns_no_reduction(self):
        amount, snap = pricing.apply_discount(
            customer=self.customer,
            code='NOT_A_REAL_CODE_XYZ',
            subtotal=Decimal('50'),
        )
        self.assertEqual(amount, Decimal('0.00'))
        self.assertIsNone(snap)


class CategoryMatchTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('60.00'))
        GarmentCategory.objects.create(name='Wedding Dress', base_price=Decimal('200.00'))

    def test_longest_matching_category_name_wins(self):
        unit, snap = pricing.quote_item(
            garment_type='Formal Wedding Dress',
            fabric='',
            priority='normal',
            quantity=1,
        )
        self.assertEqual(snap['category']['name'], 'Wedding Dress')
        self.assertEqual(unit, Decimal('200.00'))


class FreezeDiscountSyncTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        self.customer = Customer.objects.create(first_name='X', last_name='Y')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status='received',
            currency=Currency.objects.get(code='EUR'),
            exchange_rate=Decimal('1'),
            subtotal_amount=Decimal('100.00'),
            final_amount=Decimal('90.00'),
            base_subtotal=Decimal('100.00'),
            base_final=Decimal('90.00'),
            order_discount_type='fixed',
            order_discount_value=Decimal('10.00'),
        )
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('50.00'))

    def test_freeze_resets_discount_when_quote_has_none(self):
        quote = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': '', 'priority': 'normal', 'quantity': 1}],
            code='',
        )
        pricing.freeze_onto_order(self.order, quote, currency_code='EUR')
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_discount_type, 'none')
        self.assertEqual(self.order.order_discount_value, Decimal('0.00'))


@override_settings(BOOKING_MIN_DAYS_AHEAD=1)
class PortalBookingDueDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'booker', password='secret123', email='b@example.com',
        )
        self.customer = Customer.objects.create(
            user=self.user, first_name='B', last_name='K', email='b@example.com',
        )
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('50'))

    def test_rejects_due_date_today_or_past(self):
        self.client.login(username='booker', password='secret123')
        today = timezone.localdate()
        self.client.post(
            reverse('portal_book'),
            {
                'due_date': today.isoformat(),
                'garment_type': 'Dress',
                'priority': 'normal',
                'notes': '',
                'fabric': '',
                'color': '',
                'special_instructions': '',
                'quantity': '1',
                'applied_code': '',
            },
        )
        self.assertEqual(self.customer.orders.count(), 0)

    def test_invalid_discount_code_warns_but_booking_proceeds(self):
        self.client.login(username='booker', password='secret123')
        due = timezone.localdate() + timedelta(days=7)
        response = self.client.post(
            reverse('portal_book'),
            {
                'due_date': due.isoformat(),
                'garment_type': 'Dress',
                'priority': 'normal',
                'notes': '',
                'fabric': '',
                'color': '',
                'special_instructions': '',
                'quantity': '1',
                'applied_code': 'NOT_REAL_CODE_XYZ',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context['messages']]
        self.assertTrue(any('could not be applied' in m for m in msgs))
        self.assertEqual(self.customer.orders.count(), 1)


class TicketDefaultsTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        self.customer = Customer.objects.create(first_name='A', last_name='B', email='a@x.com')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            due_date=timezone.localdate() + timedelta(days=7),
            priority='urgent',
            status='received',
            customer_notes='Please hem evenly',
            notes='Internal note',
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            garment_type='Coat',
            fabric='Wool',
            special_instructions='Shorten sleeves',
            quantity=1,
        )
        Measurement.objects.create(
            order_item=self.item,
            measurement_type='chest',
            measurement_value=Decimal('100'),
            unit='cm',
        )

    def test_initial_includes_order_deadline_notes_and_measurements(self):
        data = ticket_defaults_service.initial_fields_from_order_item(self.item)
        self.assertEqual(data['deadline'], self.order.due_date)
        self.assertEqual(data['priority'], 'urgent')
        self.assertIn('Garment: Coat', data['design_notes'])
        self.assertIn('Fabric: Wool', data['design_notes'])
        self.assertIn('Please hem evenly', data['design_notes'])
        self.assertIn('Shorten sleeves', data['design_notes'])
        self.assertIn('chest', data['design_notes'])
        self.assertIn('Internal note', data['observations'])


class FrenchLocaleFallbackTests(TestCase):
    def test_french_locale_can_activate_for_requests(self):
        with translation.override('fr'):
            self.assertEqual(translation.get_language(), 'fr')


class PortalPayCurrencyContextTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        Currency.objects.create(code='USD', name='US Dollar', symbol='$')
        ExchangeRate.objects.create(
            currency=Currency.objects.get(code='USD'),
            rate_to_base=Decimal('1.10'),
        )
        self.user = User.objects.create_user('payer', password='x', email='p@x.com')
        self.customer = Customer.objects.create(
            user=self.user, first_name='P', last_name='Y', email='p@x.com',
        )
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status='received',
            currency=Currency.objects.get(code='EUR'),
            exchange_rate=Decimal('1'),
            final_amount=Decimal('25.00'),
            subtotal_amount=Decimal('25.00'),
            base_final=Decimal('25.00'),
            base_subtotal=Decimal('25.00'),
        )
        self.payment = Payment.objects.create(
            order=self.order,
            amount=Decimal('25.00'),
            payment_method='card',
            payment_stage='final',
        )

    def test_pay_page_labels_booking_currency(self):
        self.client.login(username='payer', password='x')
        response = self.client.get(reverse('portal_pay_order', kwargs={'pk': self.order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['payment_currency_label'], 'EUR')

    def test_payment_receipt_html_shows_display_currency_row(self):
        self.client.login(username='payer', password='x')
        session = self.client.session
        session[display_currency_service.SESSION_KEY_DISPLAY_CURRENCY] = 'USD'
        session.save()
        response = self.client.get(
            reverse('payment_receipt', kwargs={'payment_id': self.payment.pk}),
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('USD', content)


class ReferralDiscountOrderTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        self.buyer = Customer.objects.create(first_name='B', last_name='Y', email='buy@x.com')
        self.referrer = Customer.objects.create(
            first_name='R', last_name='F', email='ref@x.com', referral_code='CDP-REF99',
        )
        ReferralCode.objects.create(
            customer=self.referrer, code='CDP-REF99', percent=Decimal('15'),
        )
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('40'))

    def test_referral_code_reduces_quote(self):
        quote = pricing.quote_order(
            customer=self.buyer,
            items=[{'garment_type': 'Dress', 'fabric': '', 'priority': 'normal', 'quantity': 1}],
            code='CDP-REF99',
        )
        self.assertGreater(quote['discount'], Decimal('0'))
        self.assertLess(quote['final'], quote['subtotal'])


class PortalReorderDiscountTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        self.user = User.objects.create_user('reo', password='x', email='o@x.com')
        self.customer = Customer.objects.create(
            user=self.user, first_name='O', last_name='R', email='o@x.com',
        )
        self.referrer = Customer.objects.create(
            first_name='Ref', last_name='R', email='r2@x.com', referral_code='CDP-R99',
        )
        ReferralCode.objects.create(
            customer=self.referrer, code='CDP-R99', percent=Decimal('10'),
        )
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('100.00'))
        self.source = CustomerOrder.objects.create(
            customer=self.customer,
            status='received',
            payment_status='unpaid',
            due_date=timezone.localdate() + timedelta(days=14),
        )
        OrderItem.objects.create(
            order=self.source,
            garment_type='Dress',
            fabric='',
            quantity=1,
            unit_price=Decimal('100.00'),
        )
        quote = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': '', 'priority': 'normal', 'quantity': 1}],
            code='CDP-R99',
        )
        pricing.freeze_onto_order(self.source, quote, currency_code='EUR')
        item = self.source.items.first()
        item.unit_price = Decimal(quote['lines'][0]['unit_price'])
        item.save()

    def test_reorder_requotes_with_stored_discount_code(self):
        self.client.login(username='reo', password='x')
        self.client.get(reverse('portal_reorder', kwargs={'pk': self.source.pk}), follow=True)
        new_order = self.customer.orders.exclude(pk=self.source.pk).order_by('-pk').first()
        self.assertIsNotNone(new_order)
        expected = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': '', 'priority': 'normal', 'quantity': 1}],
            code='CDP-R99',
        )
        plain = pricing.quote_order(
            customer=self.customer,
            items=[{'garment_type': 'Dress', 'fabric': '', 'priority': 'normal', 'quantity': 1}],
            code='',
        )
        self.assertEqual(new_order.final_amount, expected['final'])
        self.assertLess(new_order.final_amount, plain['final'])
