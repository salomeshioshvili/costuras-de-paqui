"""Tests for public intake, lead creation, and staff conversion."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from shop.models import Currency, GarmentCategory, Lead, NotificationLog
from shop.services import intake


class IntakeFlowTests(TestCase):
    def setUp(self):
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        GarmentCategory.objects.create(name='Dress', base_price=Decimal('60'))

    def test_public_intake_post_creates_lead_and_notifies(self):
        admin = User.objects.create_user(
            'intake_admin', is_staff=True, password='x', email='admin@example.com',
        )
        response = self.client.post(reverse('public_intake'), {
            'name': 'Lara Test', 'email': 'lara@example.com',
            'garment_type': 'Dress', 'fabric': 'Silk',
            'language': 'es',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Lead.objects.filter(name='Lara Test').exists())
        self.assertTrue(NotificationLog.objects.filter(event='lead.received').exists())

    def test_convert_lead_creates_order(self):
        actor = User.objects.create_user('intake_user', password='x')
        lead = Lead.objects.create(
            name='Tomás Convert', email='tomas@example.com',
            garment_type='Dress', fabric='Silk', language='es',
        )
        order = intake.convert_lead(lead, actor=actor)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'converted')
        self.assertEqual(lead.converted_order_id, order.pk)
        self.assertGreater(order.final_amount, 0)
