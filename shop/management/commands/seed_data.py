from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from shop.models import (
    Customer, Employee, ProductionStage, CustomerOrder, OrderItem,
    Measurement, WorkTicket, TaskAssignment, TicketStatusHistory,
    Payment, Delivery, Material, OrderItemMaterial
)


class Command(BaseCommand):
    help = 'Load demo data for the sewing shop system'

    def add_arguments(self, parser):
        parser.add_argument('--no-input', '--noinput', action='store_true', dest='no_input')

    def handle(self, *args, **options):
        if ProductionStage.objects.exists():
            self.stdout.write('Demo data already exists - skipping seed.')
            return
        self.stdout.write('Seeding demo data...')

        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@stitchpro.com', 'admin123')
            self.stdout.write(self.style.SUCCESS('  [ok] Superuser: admin / admin123'))

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

        materials_data = [
            # (name, category, color, default_unit, supplier, unit_cost)
            ('Italian Wool',         'fabric', 'Navy Blue', 'm',     'Loro Piana',           Decimal('45.00')),
            ('Silk Charmeuse',       'fabric', 'Ivory',     'm',     'Mood Fabrics',         Decimal('38.00')),
            ('Satin',                'fabric', 'Red',       'm',     'Joann Fabric',         Decimal('18.00')),
            ('Cotton Poplin',        'fabric', 'White',     'm',     'Fabric.com',           Decimal('12.00')),
            ('Polyester Lining',     'lining', 'Black',     'm',     'Fabric.com',           Decimal('6.00')),
            ('Polyester Thread',     'thread', 'Navy Blue', 'spool', 'Gütermann',            Decimal('3.50')),
            ('Polyester Thread',     'thread', 'White',     'spool', 'Gütermann',            Decimal('3.50')),
            ('Polyester Thread',     'thread', 'Ivory',     'spool', 'Gütermann',            Decimal('3.50')),
            ('Polyester Thread',     'thread', 'Red',       'spool', 'Gütermann',            Decimal('3.50')),
            ('Suit Buttons',         'button', 'Horn',      'units', 'Tender Buttons',       Decimal('1.20')),
            ('Pearl Buttons',        'button', 'White',     'units', 'M&J Trimming',         Decimal('0.80')),
            ('Invisible Zipper',     'zipper', 'Red',       'units', 'YKK',                  Decimal('2.40')),
            ('Lace Trim',            'trim',   'Ivory',     'm',     'M&J Trimming',         Decimal('14.00')),
            ('Bridal Hook & Eye Set','accessory','Silver',  'units', 'M&J Trimming',         Decimal('0.50')),
        ]
        mat_objs = {}
        for name, cat, color, unit, supplier, cost in materials_data:
            m, _ = Material.objects.get_or_create(
                name=name, color=color,
                defaults={'category': cat, 'default_unit': unit,
                          'supplier': supplier, 'unit_cost': cost, 'is_active': True}
            )
            mat_objs[(name, color)] = m
        self.stdout.write(self.style.SUCCESS(f'  [ok] {len(mat_objs)} materials in catalog'))

        customers_data = [
            # (first, last, phone, email, notes, has_portal_login)
            ('Isabella', 'Martinez', '555-1001', 'isabella@email.com', 'Prefers silk and lace', True),
            ('Roberto', 'Silva',     '555-1002', 'roberto@email.com',  'Classic style, no bright colors', False),
            ('Carmen',   'Herrera',  '555-1003', 'carmen@email.com',   'Allergic to wool', False),
            ('Miguel',   'Sanchez',  '555-1004', '',                   'Prefers formal attire', False),
            ('Lucia',    'Fernandez','555-1005', 'lucia@email.com',    'Minimalist aesthetic', False),
        ]
        cust_objs = []
        for fn, ln, phone, email, notes, with_login in customers_data:
            cust_user = None
            if with_login and email:
                cust_user, created = User.objects.get_or_create(
                    username=email,
                    defaults={'email': email, 'first_name': fn, 'last_name': ln}
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
        self.stdout.write(self.style.SUCCESS(f'  [ok] {len(cust_objs)} customers (demo portal login: isabella@email.com / customer123)'))

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
            OrderItemMaterial.objects.bulk_create([
                OrderItemMaterial(order_item=item1, material=mat_objs[('Silk Charmeuse', 'Ivory')],
                                   quantity=Decimal('5.50'), unit='m'),
                OrderItemMaterial(order_item=item1, material=mat_objs[('Lace Trim', 'Ivory')],
                                   quantity=Decimal('3.00'), unit='m'),
                OrderItemMaterial(order_item=item1, material=mat_objs[('Polyester Thread', 'Ivory')],
                                   quantity=Decimal('2'), unit='spool'),
                OrderItemMaterial(order_item=item1, material=mat_objs[('Polyester Lining', 'Black')],
                                   quantity=Decimal('3.20'), unit='m', color_override='Ivory'),
                OrderItemMaterial(order_item=item1, material=mat_objs[('Bridal Hook & Eye Set', 'Silver')],
                                   quantity=Decimal('8'), unit='units'),
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
            OrderItemMaterial.objects.bulk_create([
                OrderItemMaterial(order_item=item2a, material=mat_objs[('Italian Wool', 'Navy Blue')],
                                   quantity=Decimal('3.50'), unit='m'),
                OrderItemMaterial(order_item=item2a, material=mat_objs[('Polyester Lining', 'Black')],
                                   quantity=Decimal('2.20'), unit='m'),
                OrderItemMaterial(order_item=item2a, material=mat_objs[('Suit Buttons', 'Horn')],
                                   quantity=Decimal('6'), unit='units'),
                OrderItemMaterial(order_item=item2a, material=mat_objs[('Polyester Thread', 'Navy Blue')],
                                   quantity=Decimal('2'), unit='spool'),
                OrderItemMaterial(order_item=item2b, material=mat_objs[('Cotton Poplin', 'White')],
                                   quantity=Decimal('5.00'), unit='m', notes='Two shirts'),
                OrderItemMaterial(order_item=item2b, material=mat_objs[('Pearl Buttons', 'White')],
                                   quantity=Decimal('14'), unit='units'),
                OrderItemMaterial(order_item=item2b, material=mat_objs[('Polyester Thread', 'White')],
                                   quantity=Decimal('1'), unit='spool'),
            ])
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
            self.stdout.write(self.style.SUCCESS('  [ok] Order 2: in production suit'))

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
                notes='Evening gown that is urgent because the event is on Saturday.',
                created_by=admin
            )
            item3 = OrderItem.objects.create(
                order=o3, garment_type='Evening Gown', description='Floor-length red satin gown',
                fabric='Satin', color='Red', size_label='10', quantity=1,
                unit_price=Decimal('320.00'), item_status='in_progress'
            )
            OrderItemMaterial.objects.bulk_create([
                OrderItemMaterial(order_item=item3, material=mat_objs[('Satin', 'Red')],
                                   quantity=Decimal('4.50'), unit='m'),
                OrderItemMaterial(order_item=item3, material=mat_objs[('Invisible Zipper', 'Red')],
                                   quantity=Decimal('1'), unit='units'),
                OrderItemMaterial(order_item=item3, material=mat_objs[('Polyester Thread', 'Red')],
                                   quantity=Decimal('2'), unit='spool'),
            ])
            t3 = WorkTicket.objects.create(
                order_item=item3, current_stage=stages['Finishing'],
                priority='urgent', status='in_progress',
                deadline=today - timedelta(days=2),
            )
            TaskAssignment.objects.create(ticket=t3, employee=emp_objs[3], assignment_status='current')
            Payment.objects.create(order=o3, amount=Decimal('100.00'), payment_method='cash', payment_stage='partial')
            self.stdout.write(self.style.SUCCESS('  [ok] Order 3: overdue urgent gown'))

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
        self.stdout.write(self.style.SUCCESS('Demo data loaded successfully!'))
        self.stdout.write('')
        self.stdout.write('Access URLs and credentials:')
        self.stdout.write('  Public site:       http://127.0.0.1:8000/portal/')
        self.stdout.write('  Staff dashboard:   http://127.0.0.1:8000/dashboard/   (admin / admin123)')
        self.stdout.write('  Django admin:      http://127.0.0.1:8000/admin/        (admin / admin123)')
        self.stdout.write('  Employee portal:   http://127.0.0.1:8000/staff/login/  (e.g. carlos.ruiz@stitchpro.com / staff123)')
        self.stdout.write('  Customer portal:   http://127.0.0.1:8000/portal/login/ (isabella@email.com / customer123)')
