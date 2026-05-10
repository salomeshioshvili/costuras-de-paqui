"""Additive seed data for the new tracks. Never touches the original demo data.

Run after `seed_data` (or independently). Idempotent: running twice does not duplicate
rows because everything uses get_or_create / update_or_create.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.models import (
    AddOn, Currency, Customer, DiscountRule, ExchangeRate, FabricType,
    GarmentCategory, Lead, Material, MaterialRequest, ReferralCode, StorageLocation, Supplier, UrgencySurcharge,
)


class Command(BaseCommand):
    help = 'Seed additional pricing / inventory / customer-experience data (additive only).'

    def handle(self, *args, **options):
        self._seed_currencies()
        self._seed_pricing_tables()
        self._seed_storage_and_suppliers()
        self._seed_materials()
        self._seed_referral_codes_for_existing_customers()
        self._seed_demo_lead()
        self._seed_demo_request()
        self.stdout.write(self.style.SUCCESS('seed_extras complete.'))

    # ── 1. Currencies & exchange rates ──────────────────────────────
    def _seed_currencies(self):
        currencies = [
            ('EUR', 'Euro', '€', True),
            ('USD', 'US Dollar', '$', False),
            ('GBP', 'Pound Sterling', '£', False),
            ('BRL', 'Brazilian Real', 'R$', False),
        ]
        today = timezone.now().date()
        for code, name, symbol, is_base in currencies:
            obj, _ = Currency.objects.update_or_create(
                code=code,
                defaults={'name': name, 'symbol': symbol, 'is_base': is_base},
            )
            ExchangeRate.objects.update_or_create(
                currency=obj, captured_on=today,
                defaults={'rate_to_base': {
                    'EUR': Decimal('1.000000'),
                    'USD': Decimal('1.080000'),
                    'GBP': Decimal('0.860000'),
                    'BRL': Decimal('5.300000'),
                }[code], 'source': 'seed'},
            )
        self.stdout.write('  · currencies + initial rates')

    # ── 2. Pricing rules ────────────────────────────────────────────
    def _seed_pricing_tables(self):
        cat_seed = [
            ('Dress', '60'), ('Wedding Gown', '320'), ('Suit Jacket', '120'),
            ('Trousers', '45'), ('Skirt', '40'), ('Blouse', '35'),
            ('Shirt', '30'), ('Coat', '90'), ('Alteration', '18'),
        ]
        for name, base in cat_seed:
            GarmentCategory.objects.get_or_create(
                name=name,
                defaults={'base_price': Decimal(base)},
            )
        for name, mult in [
            ('Cotton', '1.00'), ('Linen', '1.10'), ('Wool', '1.30'),
            ('Silk', '1.55'), ('Velvet', '1.45'), ('Denim', '1.10'),
        ]:
            FabricType.objects.get_or_create(
                name=name, defaults={'multiplier': Decimal(mult)},
            )
        for name, kind, price in [
            ('Lining', 'flat', '12'),
            ('Hand embroidery', 'per_unit', '25'),
            ('Beading', 'per_unit', '40'),
            ('Express turnaround', 'flat', '30'),
        ]:
            AddOn.objects.get_or_create(
                name=name, defaults={'kind': kind, 'price': Decimal(price)},
            )
        for priority, mult in [('low', '0.90'), ('normal', '1.00'),
                                ('high', '1.20'), ('urgent', '1.50')]:
            UrgencySurcharge.objects.update_or_create(
                priority=priority, defaults={'multiplier': Decimal(mult)},
            )
        for code, kind, value, label in [
            ('NEW10', 'percentage', '10', 'New customer 10% off'),
            ('LOYAL15', 'percentage', '15', 'Loyalty 15% (after 4 orders)'),
            ('SPRING25', 'fixed', '25', 'Seasonal €25 off'),
        ]:
            DiscountRule.objects.get_or_create(
                code=code,
                defaults={
                    'kind': kind, 'value': Decimal(value),
                    'label': label, 'min_orders': 4 if code == 'LOYAL15' else 0,
                },
            )
        self.stdout.write('  · pricing tables')

    # ── 3. Storage + suppliers ──────────────────────────────────────
    def _seed_storage_and_suppliers(self):
        for code, kind, area in [
            ('S-A12', 'shelf', 'Workshop A'),
            ('H-03', 'hanger', 'Fitting room'),
            ('B-07', 'bin', 'Storage room'),
            ('R-1', 'rail', 'Workshop A'),
        ]:
            StorageLocation.objects.get_or_create(
                code=code, defaults={'kind': kind, 'area': area},
            )
        Supplier.objects.get_or_create(
            name='Telas Madrid SL',
            defaults={'contact_person': 'Marta López', 'email': 'pedidos@telasmadrid.es',
                      'phone': '+34 91 123 4567', 'lead_time_days': 5},
        )
        Supplier.objects.get_or_create(
            name='Hilos del Sur',
            defaults={'contact_person': 'Carlos Ruiz', 'email': 'ventas@hilosdelsur.es',
                      'phone': '+34 95 765 4321', 'lead_time_days': 3},
        )
        self.stdout.write('  · storage + suppliers')

    # ── 4. Materials ────────────────────────────────────────────────
    def _seed_materials(self):
        telas = Supplier.objects.get(name='Telas Madrid SL')
        hilos = Supplier.objects.get(name='Hilos del Sur')
        rail = StorageLocation.objects.filter(code='R-1').first()
        seed = [
            ('Lino blanco', 'fabric', 'Crudo', 'm', '12.50', telas, '20.00', '6.00', rail),
            ('Algodón floreado', 'fabric', 'Verde', 'm', '8.20', telas, '15.00', '4.00', rail),
            ('Hilo poliéster 60', 'thread', 'Blanco', 'spool', '1.10', hilos, '40.00', '10.00', rail),
            ('Cremallera 25cm', 'zipper', 'Negro', 'unit', '0.85', hilos, '6.00', '15.00', rail),
            ('Botón nácar 18mm', 'button', 'Crema', 'unit', '0.30', hilos, '24.00', '50.00', rail),
        ]
        for name, cat, color, unit, cost, supplier, stock, threshold, location in seed:
            Material.objects.get_or_create(
                name=name, color=color,
                defaults={
                    'category': cat, 'default_unit': unit,
                    'unit_cost': Decimal(cost), 'supplier': supplier,
                    'stock_on_hand': Decimal(stock),
                    'low_stock_threshold': Decimal(threshold),
                    'location': location,
                },
            )
        self.stdout.write('  · materials')

    # ── 5. Referral codes for existing customers ────────────────────
    def _seed_referral_codes_for_existing_customers(self):
        n = 0
        for customer in Customer.objects.all():
            ref, created = ReferralCode.objects.get_or_create(
                customer=customer,
                defaults={'code': customer.referral_code, 'percent': Decimal('10.00')},
            )
            if created:
                n += 1
        self.stdout.write(f'  · referral codes (created: {n})')

    # ── 6. Sample lead ──────────────────────────────────────────────
    def _seed_demo_lead(self):
        Lead.objects.get_or_create(
            email='maria.demo@example.com',
            defaults={
                'name': 'María Demo',
                'phone': '+34 600 000 000',
                'garment_type': 'Vestido de fiesta',
                'fabric': 'Seda',
                'color': 'Rojo vino',
                'language': 'es',
                'notes': 'Talla 38 aproximada, evento dentro de 3 semanas.',
                'due_date': timezone.now().date() + timedelta(days=21),
            },
        )

    # ── 7. Sample material request ──────────────────────────────────
    def _seed_demo_request(self):
        from shop.models import Employee
        emp = Employee.objects.filter(is_active=True).first()
        mat = Material.objects.filter(name='Cremallera 25cm').first()
        if emp and mat:
            MaterialRequest.objects.get_or_create(
                requested_by=emp, material=mat,
                defaults={
                    'quantity': Decimal('5'),
                    'priority': 'high',
                    'reason': 'Necesario para finalizar 3 vestidos de la próxima semana.',
                    'status': 'pending',
                },
            )
