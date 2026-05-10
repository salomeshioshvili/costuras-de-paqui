"""Regression tests for notifications, appointments, and display currency."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.models import (
    Currency, Customer, CustomerOrder, ExchangeRate, NotificationLog,
)
from shop.services import display_currency as display_currency_service


@override_settings(
    APPOINTMENT_MIN_DAYS_AHEAD=1,
    APPOINTMENT_ALLOWED_WEEKDAYS=(0, 1, 2, 3, 4),
    APPOINTMENT_START_HOUR=9,
    APPOINTMENT_END_HOUR_EXCLUSIVE=18,
)
class NotificationMarkReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('notif_user', password='testpass123')
        NotificationLog.objects.create(
            user=self.user, channel='inapp', subject='Hello', body='Body', is_read=False,
        )

    def test_post_marks_read_without_error(self):
        self.client.login(username='notif_user', password='testpass123')
        response = self.client.post(reverse('notifications'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('notifications'))
        self.assertFalse(
            NotificationLog.objects.filter(user=self.user, is_read=False).exists()
        )


@override_settings(
    APPOINTMENT_MIN_DAYS_AHEAD=1,
    APPOINTMENT_ALLOWED_WEEKDAYS=(0, 1, 2, 3, 4),
    APPOINTMENT_START_HOUR=9,
    APPOINTMENT_END_HOUR_EXCLUSIVE=18,
)
class AppointmentValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cust_appt', password='testpass123', email='c@example.com')
        self.customer = Customer.objects.create(
            user=self.user, first_name='C', last_name='A', email='c@example.com',
        )

    def test_rejects_same_calendar_day(self):
        self.client.login(username='cust_appt', password='testpass123')
        local = timezone.localtime()
        when = timezone.make_aware(
            datetime.combine(local.date(), datetime.min.time().replace(hour=15)),
            timezone.get_current_timezone(),
        )
        before = self.customer.appointments.count()
        self.client.post(
            reverse('portal_appointments'),
            {'kind': 'fitting', 'scheduled_at': when.isoformat(), 'notes': ''},
        )
        self.assertEqual(self.customer.appointments.count(), before)

    def test_accepts_valid_weekday_slot(self):
        self.client.login(username='cust_appt', password='testpass123')
        local = timezone.localtime()
        target_date = local.date() + timedelta(days=1)
        while (
            target_date <= local.date()
            or target_date.weekday() not in settings.APPOINTMENT_ALLOWED_WEEKDAYS
        ):
            target_date += timedelta(days=1)
        when = timezone.make_aware(
            datetime.combine(target_date, datetime.min.time().replace(hour=10)),
            timezone.get_current_timezone(),
        )
        before = self.customer.appointments.count()
        self.client.post(
            reverse('portal_appointments'),
            {'kind': 'fitting', 'scheduled_at': when.isoformat(), 'notes': ''},
        )
        self.assertGreater(self.customer.appointments.count(), before)


class DisplayCurrencyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('cur_user', password='x', email='u@example.com')
        eur = Currency.objects.create(code='EUR', name='Euro', symbol='€', is_base=True)
        usd = Currency.objects.create(code='USD', name='US Dollar', symbol='$', is_base=False)
        ExchangeRate.objects.create(currency=usd, rate_to_base=Decimal('1.100000'))
        self.customer = Customer.objects.create(
            user=self.user, first_name='U', last_name='M', email='u@example.com',
            preferred_currency=eur,
        )
        self.order = CustomerOrder.objects.create(
            customer=self.customer, status='received',
            currency=eur, exchange_rate=Decimal('1'),
            subtotal_amount=Decimal('100.00'), final_amount=Decimal('100.00'),
            base_subtotal=Decimal('100.00'), base_final=Decimal('100.00'),
        )

    def test_session_currency_updates_display_amount(self):
        session = self.client.session
        session[display_currency_service.SESSION_KEY_DISPLAY_CURRENCY] = 'USD'
        session.save()
        self.client.login(username='cur_user', password='x')
        out = display_currency_service.convert_booking_amount_for_display(
            self.order, Decimal('100.00'), 'USD',
        )
        self.assertEqual(out, Decimal('110.00'))

    def test_set_display_currency_requires_login(self):
        response = self.client.post(reverse('set_display_currency'), {'currency': 'USD'})
        self.assertEqual(response.status_code, 302)
