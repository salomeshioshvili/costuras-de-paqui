"""Workflow + audit tests."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from shop import workflow
from shop.models import (
    AuditLog, Customer, CustomerOrder, OrderItem, ProductionStage, WorkTicket,
)


class WorkflowTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('w_admin', password='x')
        self.customer = Customer.objects.create(first_name='W', last_name='Test')
        self.order = CustomerOrder.objects.create(
            customer=self.customer, status='received',
            final_amount=Decimal('100.00'), base_final=Decimal('100.00'),
        )

    def test_invalid_transition_raises(self):
        with self.assertRaises(workflow.InvalidTransition):
            workflow.transition(self.order, to='delivered', actor=self.user)

    def test_valid_transition_writes_audit(self):
        workflow.transition(self.order, to='in_production', actor=self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'in_production')
        self.assertTrue(
            AuditLog.objects.filter(
                target_type='customerorder', target_id=self.order.pk,
                action='customerorder.transition',
            ).exists()
        )

    def test_delivered_requires_delivery_record(self):
        workflow.transition(self.order, to='in_production', actor=self.user)
        item = OrderItem.objects.create(order=self.order, garment_type='Dress')
        item.item_status = 'completed'
        item.save(update_fields=['item_status'])
        workflow.transition(self.order, to='completed', actor=self.user)
        workflow.transition(self.order, to='ready_for_delivery', actor=self.user)
        with self.assertRaises(workflow.TransitionBlocked):
            workflow.transition(self.order, to='delivered', actor=self.user)

    def test_schedule_delivery_only_when_ready(self):
        with self.assertRaises(workflow.TransitionBlocked):
            workflow.schedule_delivery(
                self.order, delivery_date=timezone.now().date(),
                delivery_method='pickup', actor=self.user,
            )

    def test_next_states_offers_only_legal_targets(self):
        targets = [v for v, label, reason in workflow.next_states(self.order)]
        self.assertIn('in_production', targets)
        self.assertNotIn('delivered', targets)


class TicketWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('t_admin', password='x')
        self.customer = Customer.objects.create(first_name='T', last_name='Case')
        self.order = CustomerOrder.objects.create(
            customer=self.customer, status='in_production',
            final_amount=Decimal('60'), base_final=Decimal('60'),
        )
        self.item = OrderItem.objects.create(order=self.order, garment_type='Blouse')
        self.stage = ProductionStage.objects.create(stage_name='Cutting', stage_order=1)
        self.ticket = WorkTicket.objects.create(
            order_item=self.item, current_stage=self.stage,
            ticket_code='T-TEST', deadline=timezone.now().date() + timedelta(days=5),
        )

    def test_ticket_completion_cascades_to_order(self):
        workflow.transition(self.ticket, to='in_progress', actor=self.user)
        workflow.transition(self.ticket, to='completed', actor=self.user)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'completed')
