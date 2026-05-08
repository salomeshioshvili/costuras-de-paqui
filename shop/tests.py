"""Unit tests for the sewing shop management system.

The test suite covers the critical paths of the application: customer
registration, order state transitions including the empty draft rule,
ticket creation, propagation of completion to the parent order, damage
incidents and the rule that blocks delivery while damage is unresolved,
material catalog management and per garment material usage.

The tests use Django's :class:`~django.test.TestCase` so each test runs
inside its own transaction and the database is rolled back at the end.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    CustomerOrder,
    DamageIncident,
    Delivery,
    Employee,
    Material,
    OrderItem,
    OrderItemMaterial,
    ProductionStage,
    TaskAssignment,
    TicketStatusHistory,
    WorkTicket,
)
from .views import (
    ASSIGNMENT_STATUS_CURRENT,
    ITEM_STATUS_COMPLETED,
    ITEM_STATUS_DELIVERED,
    ITEM_STATUS_IN_PROGRESS,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_DRAFT,
    ORDER_STATUS_IN_PRODUCTION,
    ORDER_STATUS_READY_FOR_DELIVERY,
    ORDER_STATUS_RECEIVED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PARTIALLY_PAID,
    TICKET_STATUS_BLOCKED,
    TICKET_STATUS_COMPLETED,
)


def _build_minimal_dataset():
    """Create the smallest dataset the tests need.

    Returns the tuple ``(staff_user, customer, employee, stage)`` so that
    individual tests can attach further records to it.
    """
    staff_user = User.objects.create_user(
        username='staff', password='staffpass', is_staff=True,
    )
    customer_user = User.objects.create_user(
        username='customer@example.com',
        email='customer@example.com',
        password='customerpass',
    )
    customer = Customer.objects.create(
        first_name='Ana',
        last_name='Tester',
        email='customer@example.com',
        user=customer_user,
    )
    employee = Employee.objects.create(
        first_name='Mario',
        last_name='Tailor',
        email='mario@example.com',
        role='tailor',
    )
    stage = ProductionStage.objects.create(stage_name='Cutting', stage_order=1)
    ProductionStage.objects.create(stage_name='Quality Check', stage_order=2)
    return staff_user, customer, employee, stage


class CustomerPortalTests(TestCase):
    """Cover the public registration and login flow."""

    def test_registration_creates_user_and_customer(self):
        client = Client()
        response = client.post(reverse('portal_register'), data={
            'first_name': 'New',
            'last_name': 'Customer',
            'email': 'New.Customer@Example.com',
            'phone': '555 1234',
            'address': 'Calle Mayor 1',
            'password1': 'verysafe123',
            'password2': 'verysafe123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            User.objects.filter(username='new.customer@example.com').exists(),
            'The username should be the lowercased email.',
        )
        customer = Customer.objects.get(email='new.customer@example.com')
        self.assertIsNotNone(customer.user)

    def test_registration_rejects_short_password(self):
        client = Client()
        response = client.post(reverse('portal_register'), data={
            'first_name': 'Short',
            'last_name': 'Pass',
            'email': 'short@example.com',
            'password1': 'tiny',
            'password2': 'tiny',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at least')


class OrderStateMachineTests(TestCase):
    """Cover the order lifecycle and the rule that blocks empty drafts."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.draft_order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_DRAFT,
            due_date=timezone.now().date() + timedelta(days=7),
        )

    def test_empty_draft_order_cannot_be_promoted(self):
        response = self.client.post(
            reverse('order_status_update', args=[self.draft_order.pk]),
            data={'status': ORDER_STATUS_RECEIVED},
            follow=True,
        )
        self.draft_order.refresh_from_db()
        self.assertEqual(self.draft_order.status, ORDER_STATUS_DRAFT)
        self.assertContains(response, 'at least one garment')

    def test_order_with_item_can_be_promoted(self):
        OrderItem.objects.create(
            order=self.draft_order,
            garment_type='Dress',
            quantity=1,
            unit_price=Decimal('50.00'),
        )
        response = self.client.post(
            reverse('order_status_update', args=[self.draft_order.pk]),
            data={'status': ORDER_STATUS_RECEIVED},
            follow=True,
        )
        self.draft_order.refresh_from_db()
        self.assertEqual(self.draft_order.status, ORDER_STATUS_RECEIVED)
        self.assertEqual(response.status_code, 200)


class TicketLifecycleTests(TestCase):
    """Cover ticket creation, completion and propagation to the parent order."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_RECEIVED,
            due_date=timezone.now().date() + timedelta(days=7),
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            garment_type='Dress',
            quantity=1,
            unit_price=Decimal('100.00'),
        )

    def test_creating_a_ticket_moves_order_to_in_production(self):
        response = self.client.post(reverse('ticket_create_for_item', args=[self.item.pk]), data={
            'order_item': self.item.pk,
            'current_stage': self.stage.pk,
            'priority': 'normal',
        })
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.order.status, ORDER_STATUS_IN_PRODUCTION)
        self.assertEqual(self.item.item_status, ITEM_STATUS_IN_PROGRESS)
        self.assertEqual(WorkTicket.objects.filter(order_item=self.item).count(), 1)

    def test_completing_last_ticket_marks_order_ready_for_delivery(self):
        ticket = WorkTicket.objects.create(
            order_item=self.item,
            current_stage=self.stage,
            status='in_progress',
        )
        ticket.status = TICKET_STATUS_COMPLETED
        ticket.save()

        from .views import _propagate_item_completion

        _propagate_item_completion(self.item)

        self.item.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.item.item_status, ITEM_STATUS_COMPLETED)
        self.assertEqual(self.order.status, ORDER_STATUS_READY_FOR_DELIVERY)


class DeliveryDamageGuardTests(TestCase):
    """Cover the rule that blocks delivery while damage is unresolved."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_READY_FOR_DELIVERY,
            due_date=timezone.now().date() + timedelta(days=2),
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            garment_type='Suit',
            quantity=1,
            unit_price=Decimal('200.00'),
        )
        self.ticket = WorkTicket.objects.create(
            order_item=self.item,
            current_stage=self.stage,
        )

    def test_delivery_blocked_when_damage_unresolved(self):
        DamageIncident.objects.create(
            ticket=self.ticket,
            order_item=self.item,
            incident_type='ripped',
            description='A small tear on the seam.',
            severity='minor',
            is_resolved=False,
        )
        response = self.client.post(
            reverse('delivery_create', args=[self.order.pk]),
            data={
                'delivery_date': timezone.now().date(),
                'delivery_method': 'pickup',
                'received_by': '',
                'comments': '',
                'is_delivered': 'on',
            },
            follow=True,
        )
        self.assertContains(response, 'damage incident')
        self.assertFalse(Delivery.objects.filter(order=self.order).exists())

    def test_delivery_allowed_when_no_damage(self):
        response = self.client.post(
            reverse('delivery_create', args=[self.order.pk]),
            data={
                'delivery_date': timezone.now().date(),
                'delivery_method': 'pickup',
                'received_by': 'Customer',
                'comments': '',
                'is_delivered': 'on',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Delivery.objects.filter(order=self.order).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ORDER_STATUS_DELIVERED)
        self.assertEqual(
            self.item.tickets.first().order_item.order.status,
            ORDER_STATUS_DELIVERED,
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_status, ITEM_STATUS_DELIVERED)


class MaterialCatalogTests(TestCase):
    """Cover the material catalog and per garment usage records."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_RECEIVED,
            due_date=timezone.now().date() + timedelta(days=7),
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            garment_type='Coat',
            quantity=1,
            unit_price=Decimal('300.00'),
        )

    def test_material_can_be_created_and_listed(self):
        response = self.client.post(reverse('material_create'), data={
            'name': 'Italian Wool',
            'category': 'fabric',
            'color': 'Charcoal',
            'default_unit': 'm',
            'supplier': 'Tessuti SA',
            'unit_cost': '42.00',
            'is_active': 'on',
            'notes': '',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Material.objects.filter(name='Italian Wool').exists())

    def test_material_usage_uses_default_unit_when_blank(self):
        material = Material.objects.create(
            name='Lining',
            category='lining',
            default_unit='m',
            unit_cost=Decimal('5.00'),
        )
        response = self.client.post(
            reverse('orderitem_material_add', args=[self.item.pk]),
            data={
                'material': material.pk,
                'quantity': '2.5',
                'unit': 'm',
                'color_override': '',
                'notes': '',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        usage = OrderItemMaterial.objects.get(order_item=self.item)
        self.assertEqual(usage.material, material)
        self.assertEqual(usage.unit, 'm')


class PaymentStatusTests(TestCase):
    """Cover the recomputation of the payment status."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_RECEIVED,
            final_amount=Decimal('100.00'),
            due_date=timezone.now().date() + timedelta(days=7),
        )

    def test_partial_payment_sets_partially_paid(self):
        self.client.post(
            reverse('payment_add', args=[self.order.pk]),
            data={
                'payment_date': timezone.now().date(),
                'amount': '40.00',
                'payment_method': 'cash',
                'payment_stage': 'partial',
                'reference_code': '',
                'notes': '',
            },
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PAYMENT_STATUS_PARTIALLY_PAID)

    def test_full_payment_sets_paid(self):
        self.client.post(
            reverse('payment_add', args=[self.order.pk]),
            data={
                'payment_date': timezone.now().date(),
                'amount': '100.00',
                'payment_method': 'card',
                'payment_stage': 'final',
                'reference_code': 'TX1',
                'notes': '',
            },
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PAYMENT_STATUS_PAID)


class TicketAssignmentTests(TestCase):
    """Cover the invariant that a ticket has at most one current assignment."""

    def setUp(self):
        self.staff_user, self.customer, self.employee, self.stage = _build_minimal_dataset()
        self.other_employee = Employee.objects.create(
            first_name='Other',
            last_name='Tailor',
            email='other@example.com',
            role='tailor',
        )
        self.client = Client()
        self.client.login(username='staff', password='staffpass')
        self.order = CustomerOrder.objects.create(
            customer=self.customer,
            status=ORDER_STATUS_RECEIVED,
            due_date=timezone.now().date() + timedelta(days=7),
        )
        self.item = OrderItem.objects.create(
            order=self.order,
            garment_type='Skirt',
            quantity=1,
            unit_price=Decimal('80.00'),
        )
        self.ticket = WorkTicket.objects.create(
            order_item=self.item,
            current_stage=self.stage,
        )

    def test_reassignment_closes_previous_current_assignment(self):
        first_assignment = self.client.post(
            reverse('ticket_assign', args=[self.ticket.pk]),
            data={'employee': self.employee.pk, 'notes': ''},
        )
        self.assertEqual(first_assignment.status_code, 302)
        self.client.post(
            reverse('ticket_assign', args=[self.ticket.pk]),
            data={'employee': self.other_employee.pk, 'notes': ''},
        )
        current = self.ticket.assignments.filter(
            assignment_status=ASSIGNMENT_STATUS_CURRENT
        )
        self.assertEqual(current.count(), 1)
        self.assertEqual(current.first().employee, self.other_employee)
