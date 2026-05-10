from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from datetime import date, timedelta
from decimal import Decimal
from shop.models import (
    Customer, Employee, ProductionStage, CustomerOrder, OrderItem,
    Measurement, WorkTicket, TaskAssignment, TicketStatusHistory,
    Payment, Delivery
)


class Command(BaseCommand):
    help = 'Load demo data for the sewing shop system'

    def add_arguments(self, parser):
        parser.add_argument('--no-input', '--noinput', action='store_true', dest='no_input')

    def handle(self, *args, **options):
        if ProductionStage.objects.exists():
            self.stdout.write('Demo data already exists; backfilling missing customer or employee user links only.')
            self._backfill_user_links()
            return
        self.stdout.write('Seeding demo data...')

        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@stitchpro.com', 'admin123')

        stages_data = [
            ('Order Received', 1, 'Initial stage when order is placed'),
            ('Design Confirmed', 2, 'Design and specifications approved by customer'),
            ('Cutting', 3, 'Fabric cutting stage'),
            ('Sewing', 4, 'Main sewing production'),
            ('Finishing', 5, 'Finishing touches, buttons, zippers'),
            ('Quality Check', 6, 'Quality control inspection'),
            ('Ready for Delivery', 7, 'Production complete, awaiting delivery'),
            ('Delivered', 8, 'Delivered to customer'),
        ]
        stages = {}
        for name, order, desc in stages_data:
            s, _ = ProductionStage.objects.get_or_create(
                stage_name=name, defaults={'stage_order': order, 'description': desc}
            )
            stages[name] = s
        self.stdout.write(self.style.SUCCESS(f'  [ok] {len(stages)} production stages'))

        employees_data = [
            ('Maria', 'Lopez', 'manager', '555-0100', 'Bridal and formalwear'),
            ('Carlos', 'Ruiz', 'tailor', '555-0101', 'Suits and trousers'),
            ('Ana', 'Torres', 'cutter', '555-0102', 'Precision cutting'),
            ('Luis', 'Morales', 'finisher', '555-0103', 'Embroidery and finishing'),
            ('Sofia', 'Reyes', 'quality_control', '555-0104', 'Quality assurance'),
            ('Diego', 'Vega', 'receptionist', '555-0105', 'Customer service'),
        ]
        emp_objs = []
        for fn, ln, role, phone, specialty in employees_data:
            email = f"{fn.lower()}.{ln.lower()}@stitchpro.com"
            # Create a linked user account for each employee
            emp_user, _ = User.objects.get_or_create(
                username=email,
                defaults={'email': email, 'first_name': fn, 'last_name': ln}
            )
            if _:
                emp_user.set_password('staff123')
                emp_user.save()
            e, _ = Employee.objects.get_or_create(
                first_name=fn, last_name=ln,
                defaults={'role': role, 'phone': phone, 'specialty': specialty, 'is_active': True, 'email': email, 'user': emp_user}
            )
            if not e.user:
                e.user = emp_user
                e.save()
            emp_objs.append(e)
        self.stdout.write(self.style.SUCCESS(f'  [ok] {len(emp_objs)} employees (password: staff123)'))

        customers_data = [
            ('Isabella', 'Martinez', '555-1001', 'isabella@email.com', 'Prefers silk and lace'),
            ('Roberto', 'Silva', '555-1002', 'roberto@email.com', 'Classic style, no bright colors'),
            ('Carmen', 'Herrera', '555-1003', 'carmen@email.com', 'Allergic to wool'),
            ('Miguel', 'Sanchez', '555-1004', '', 'Prefers formal attire'),
            ('Lucia', 'Fernandez', '555-1005', 'lucia@email.com', 'Minimalist aesthetic'),
        ]
        cust_objs = []
        for fn, ln, phone, email, notes in customers_data:
            cust_user = None
            if email:
                cust_user, created = User.objects.get_or_create(
                    username=email,
                    defaults={'email': email, 'first_name': fn, 'last_name': ln},
                )
                if created:
                    cust_user.set_password('customer123')
                    cust_user.save()
            c, _ = Customer.objects.get_or_create(
                first_name=fn, last_name=ln,
                defaults={'phone': phone, 'email': email, 'notes': notes, 'user': cust_user}
            )
            if cust_user and not c.user:
                c.user = cust_user
                c.save(update_fields=['user'])
            cust_objs.append(c)
        self.stdout.write(self.style.SUCCESS(f'  [ok] {len(cust_objs)} customers (demo portal: isabella@email.com / customer123)'))

        admin = User.objects.get(username='admin')
        today = date.today()

        if not CustomerOrder.objects.filter(customer=cust_objs[0]).exists():
            o1 = CustomerOrder.objects.create(
                customer=cust_objs[0],
                order_date=today - timedelta(days=20),
                due_date=today - timedelta(days=5),
                status='delivered',
                priority='high',
                subtotal_amount=Decimal('450.00'),
                final_amount=Decimal('430.00'),
                order_discount_type='fixed',
                order_discount_value=Decimal('20.00'),
                payment_option='deposit_and_final',
                payment_status='paid',
                notes='Bridal gown for wedding on the 15th.',
                created_by=admin
            )
            item1 = OrderItem.objects.create(
                order=o1, garment_type='Wedding Gown', description='Silk ivory gown with lace trim',
                fabric='Silk', color='Ivory', size_label='8', quantity=1,
                unit_price=Decimal('450.00'), item_status='delivered'
            )
            Measurement.objects.bulk_create([
                Measurement(order_item=item1, measurement_type='bust', measurement_value=88, unit='cm'),
                Measurement(order_item=item1, measurement_type='waist', measurement_value=68, unit='cm'),
                Measurement(order_item=item1, measurement_type='hip', measurement_value=94, unit='cm'),
                Measurement(order_item=item1, measurement_type='length', measurement_value=160, unit='cm'),
            ])
            t1 = WorkTicket.objects.create(
                order_item=item1, current_stage=stages['Delivered'],
                priority='high', status='completed',
                deadline=today - timedelta(days=6),
                design_notes='Cathedral train, sweetheart neckline'
            )
            for stage_name in ['Order Received', 'Design Confirmed', 'Cutting', 'Sewing', 'Finishing', 'Quality Check', 'Ready for Delivery', 'Delivered']:
                TicketStatusHistory.objects.create(ticket=t1, stage=stages[stage_name], changed_by=emp_objs[0])
            Payment.objects.create(order=o1, amount=Decimal('200.00'), payment_method='card', payment_stage='deposit', payment_date=today - timedelta(days=20))
            Payment.objects.create(order=o1, amount=Decimal('230.00'), payment_method='cash', payment_stage='final', payment_date=today - timedelta(days=5))
            Delivery.objects.create(order=o1, delivery_date=today - timedelta(days=5), delivery_method='pickup', received_by='Isabella Martinez', is_delivered=True)
            self.stdout.write(self.style.SUCCESS('  [ok] Order 1: Delivered bridal gown'))

        if not CustomerOrder.objects.filter(customer=cust_objs[1]).exists():
            o2 = CustomerOrder.objects.create(
                customer=cust_objs[1],
                order_date=today - timedelta(days=7),
                due_date=today + timedelta(days=5),
                status='in_production',
                priority='normal',
                subtotal_amount=Decimal('680.00'),
                final_amount=Decimal('680.00'),
                payment_option='full_on_delivery',
                payment_status='unpaid',
                notes='Classic navy suit for business use.',
                created_by=admin
            )
            item2a = OrderItem.objects.create(
                order=o2, garment_type='Business Suit', description='Double-breasted navy suit',
                fabric='Wool Blend', color='Navy Blue', size_label='44', quantity=1,
                unit_price=Decimal('480.00'), item_status='in_progress'
            )
            item2b = OrderItem.objects.create(
                order=o2, garment_type='Dress Shirt', description='White poplin shirt',
                fabric='Cotton', color='White', size_label='L', quantity=2,
                unit_price=Decimal('100.00'), item_status='pending'
            )
            Measurement.objects.bulk_create([
                Measurement(order_item=item2a, measurement_type='chest', measurement_value=100, unit='cm'),
                Measurement(order_item=item2a, measurement_type='waist', measurement_value=86, unit='cm'),
                Measurement(order_item=item2a, measurement_type='shoulder', measurement_value=46, unit='cm'),
                Measurement(order_item=item2a, measurement_type='inseam', measurement_value=82, unit='cm'),
            ])
            t2 = WorkTicket.objects.create(
                order_item=item2a, current_stage=stages['Sewing'],
                priority='normal', status='in_progress',
                deadline=today + timedelta(days=4),
                design_notes='Double-breasted, 2-button, notch lapel'
            )
            TaskAssignment.objects.create(ticket=t2, employee=emp_objs[1], assignment_status='current')
            for sn in ['Order Received', 'Design Confirmed', 'Cutting', 'Sewing']:
                TicketStatusHistory.objects.create(ticket=t2, stage=stages[sn], changed_by=emp_objs[1])
            self.stdout.write(self.style.SUCCESS('  [ok] Order 2: In-production suit'))

        if not CustomerOrder.objects.filter(customer=cust_objs[2]).exists():
            o3 = CustomerOrder.objects.create(
                customer=cust_objs[2],
                order_date=today - timedelta(days=14),
                due_date=today - timedelta(days=2),
                status='in_production',
                priority='urgent',
                subtotal_amount=Decimal('320.00'),
                final_amount=Decimal('320.00'),
                payment_option='partial_payments',
                payment_status='partially_paid',
                notes='Evening gown; URGENT: event on Saturday.',
                created_by=admin
            )
            item3 = OrderItem.objects.create(
                order=o3, garment_type='Evening Gown', description='Floor-length red satin gown',
                fabric='Satin', color='Red', size_label='10', quantity=1,
                unit_price=Decimal('320.00'), item_status='in_progress'
            )
            t3 = WorkTicket.objects.create(
                order_item=item3, current_stage=stages['Finishing'],
                priority='urgent', status='in_progress',
                deadline=today - timedelta(days=2),
            )
            TaskAssignment.objects.create(ticket=t3, employee=emp_objs[3], assignment_status='current')
            Payment.objects.create(order=o3, amount=Decimal('100.00'), payment_method='cash', payment_stage='partial')
            self.stdout.write(self.style.SUCCESS('  [ok] Order 3: OVERDUE urgent gown'))

        if not CustomerOrder.objects.filter(customer=cust_objs[3]).exists():
            o4 = CustomerOrder.objects.create(
                customer=cust_objs[3],
                order_date=today,
                due_date=today + timedelta(days=14),
                status='received',
                priority='normal',
                subtotal_amount=Decimal('0.00'),
                final_amount=Decimal('0.00'),
                payment_option='full_on_delivery',
                payment_status='unpaid',
                created_by=admin
            )
            self.stdout.write(self.style.SUCCESS('  [ok] Order 4: New received order'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Demo data loaded successfully.'))
        self.stdout.write('')
        self.stdout.write('Login credentials:')
        self.stdout.write('  Admin panel: http://127.0.0.1:8000/admin/')
        self.stdout.write('  App: http://127.0.0.1:8000/')
        self.stdout.write('  Username: admin')
        self.stdout.write('  Password: admin123')

    def _backfill_user_links(self):
        """Idempotent: create User accounts and link them to any seeded
        Customer/Employee that is missing the link. Safe to re-run."""
        from django.contrib.auth.models import User
        linked_customers = 0
        for c in Customer.objects.filter(user__isnull=True).exclude(email=''):
            user, created = User.objects.get_or_create(
                username=c.email,
                defaults={'email': c.email, 'first_name': c.first_name, 'last_name': c.last_name},
            )
            if created:
                user.set_password('customer123')
                user.save()
            c.user = user
            c.save(update_fields=['user'])
            linked_customers += 1
        linked_employees = 0
        for e in Employee.objects.filter(user__isnull=True).exclude(email=''):
            user, created = User.objects.get_or_create(
                username=e.email,
                defaults={'email': e.email, 'first_name': e.first_name, 'last_name': e.last_name},
            )
            if created:
                user.set_password('staff123')
                user.save()
            e.user = user
            e.save(update_fields=['user'])
            linked_employees += 1
        if linked_customers or linked_employees:
            self.stdout.write(self.style.SUCCESS(
                f'  [ok] Linked users: {linked_customers} customers, {linked_employees} employees.'
            ))
        else:
            self.stdout.write('  [ok] All customers/employees already have user links.')
