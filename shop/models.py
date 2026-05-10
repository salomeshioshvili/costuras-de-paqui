from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
import secrets


class Customer(models.Model):
    LANGUAGE_CHOICES = [
        ('es', 'Español'),
        ('en', 'English'),
        ('fr', 'Français'),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='es')
    referral_code = models.CharField(max_length=12, unique=True, blank=True,
                                      default='')
    preferred_currency = models.ForeignKey(
        'Currency', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='preferring_customers',
    )
    preferred_pickup_location = models.ForeignKey(
        'StorageLocation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='preferring_customers',
    )
    preferred_styles = models.JSONField(default=dict, blank=True,
                                        help_text='Saved garment style preferences as JSON')
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='customer_profile',
        help_text='Link to a system user account if this customer logs in via the portal',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self._generate_referral_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_referral_code():
        for _ in range(5):
            code = 'CDP-' + secrets.token_hex(3).upper()
            if not Customer.objects.filter(referral_code=code).exists():
                return code
        return 'CDP-' + secrets.token_hex(4).upper()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_orders(self):
        return self.orders.count()

    @property
    def active_orders(self):
        return self.orders.exclude(status__in=['delivered', 'cancelled']).count()

    @property
    def completed_order_count(self):
        return self.orders.filter(status='delivered').count()

    @property
    def lifetime_spend(self):
        total = self.orders.exclude(status='cancelled').aggregate(
            t=models.Sum('base_final')
        )['t']
        return total or Decimal('0.00')

    @property
    def loyalty_tier(self):
        """Derived tier — never stored. Recomputed from completed orders + spend."""
        completed = self.completed_order_count
        spend = self.lifetime_spend
        if completed >= 10 or spend >= Decimal('2000'):
            return 'gold'
        if completed >= 4 or spend >= Decimal('500'):
            return 'silver'
        if completed >= 1:
            return 'bronze'
        return 'new'


class Employee(models.Model):
    ROLE_CHOICES = [
        ('manager', 'Manager'),
        ('receptionist', 'Receptionist'),
        ('tailor', 'Tailor'),
        ('cutter', 'Cutter'),
        ('finisher', 'Finisher'),
        ('quality_control', 'Quality Control'),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='tailor')
    specialty = models.CharField(max_length=200, blank=True)
    hire_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 help_text='Link to a system user account if this employee logs in')

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_role_display()})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def current_assignments(self):
        return self.task_assignments.filter(assignment_status='current').count()


class EmployeeAvailability(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('unavailable', 'Unavailable'),
        ('leave', 'Leave'),
        ('sick', 'Sick'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='availability_records')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']
        verbose_name = 'Employee Availability'
        verbose_name_plural = 'Employee Availability Records'
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee.full_name} — {self.date} ({self.get_status_display()})"


class ProductionStage(models.Model):
    stage_name = models.CharField(max_length=100, unique=True)
    stage_order = models.PositiveIntegerField(help_text='Lower number = earlier stage')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['stage_order']
        verbose_name = 'Production Stage'
        verbose_name_plural = 'Production Stages'

    def __str__(self):
        return f"{self.stage_order}. {self.stage_name}"


class CustomerOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('received', 'Received'),
        ('in_production', 'In Production'),
        ('completed', 'Completed'),
        ('ready_for_delivery', 'Ready for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    PAYMENT_OPTION_CHOICES = [
        ('full_advance', 'Full Advance'),
        ('deposit_and_final', 'Deposit + Final Payment'),
        ('partial_payments', 'Partial Payments'),
        ('full_on_delivery', 'Full on Delivery'),
        ('immediate_full', 'Immediate Full'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('waived', 'Waived'),
    ]

    DISCOUNT_TYPE_CHOICES = [
        ('none', 'No Discount'),
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders')
    order_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    order_discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPE_CHOICES, default='none')
    order_discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    applied_discount_code = models.CharField(max_length=40, blank=True,
        help_text='Referral or discount code that was applied at booking time.')
    currency = models.ForeignKey('Currency', on_delete=models.PROTECT,
        null=True, blank=True, related_name='orders',
        help_text='Display currency at booking time. Frozen.')
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6,
        default=Decimal('1.000000'),
        help_text='Rate from order currency to base (EUR) at booking. Frozen.')
    base_subtotal = models.DecimalField(max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        help_text='Subtotal converted to base currency at booking. Frozen.')
    base_final = models.DecimalField(max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        help_text='Final amount converted to base currency at booking. Frozen.')
    pricing_snapshot = models.JSONField(default=dict, blank=True,
        help_text='Frozen snapshot of every pricing rule and rate used. Read-only after booking.')
    payment_option = models.CharField(max_length=20, choices=PAYMENT_OPTION_CHOICES, default='full_on_delivery')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    notes = models.TextField(blank=True)
    customer_notes = models.TextField(blank=True,
        help_text='Notes shared by the customer at booking; flow into all child tickets as design notes.')
    attachments = GenericRelation('Attachment', related_query_name='order')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer Order'
        verbose_name_plural = 'Customer Orders'

    def __str__(self):
        return f"Order #{self.pk} — {self.customer.full_name} ({self.get_status_display()})"

    @property
    def is_overdue(self):
        if self.due_date and self.status not in ['delivered', 'cancelled']:
            return self.due_date < timezone.now().date()
        return False

    @property
    def total_paid(self):
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    def recalculate_amounts(self):
        """Recalculate subtotal and final amount from order items."""
        line_total_expression = models.ExpressionWrapper(
            (models.F('unit_price') * models.F('quantity')) - models.F('item_discount'),
            output_field=models.DecimalField(max_digits=12, decimal_places=2),
        )
        subtotal = self.items.aggregate(
            total=models.Sum(line_total_expression)
        )['total'] or Decimal('0.00')
        self.subtotal_amount = subtotal

        if self.order_discount_type == 'percentage':
            discount = subtotal * (self.order_discount_value / 100)
        elif self.order_discount_type == 'fixed':
            discount = self.order_discount_value
        else:
            discount = Decimal('0.00')

        self.final_amount = max(subtotal - discount, Decimal('0.00'))
        self.save(update_fields=['subtotal_amount', 'final_amount'])


class OrderItem(models.Model):
    ITEM_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('damaged', 'Damaged'),
        ('remake_required', 'Remake Required'),
        ('cancelled', 'Cancelled'),
        ('delivered', 'Delivered'),
    ]

    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='items')
    garment_type = models.CharField(max_length=150, help_text='e.g. Dress, Suit, Blouse')
    description = models.TextField(blank=True)
    fabric = models.CharField(max_length=150, blank=True)
    color = models.CharField(max_length=100, blank=True)
    size_label = models.CharField(max_length=50, blank=True, help_text='e.g. S, M, L, XL or custom')
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    item_discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'),
                                         help_text='Item-level discount amount')
    item_status = models.CharField(max_length=20, choices=ITEM_STATUS_CHOICES, default='pending')
    special_instructions = models.TextField(blank=True)
    storage_location = models.ForeignKey(
        'StorageLocation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stored_items',
        help_text='Where the physical garment is stored.',
    )
    attachments = GenericRelation('Attachment', related_query_name='order_item')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Order Item'
        verbose_name_plural = 'Order Items'

    def __str__(self):
        return f"{self.garment_type} (Order #{self.order_id}) — {self.get_item_status_display()}"

    @staticmethod
    def _match_any_keyword(text_value, keywords):
        normalized_text = (text_value or '').lower()
        return any(keyword in normalized_text for keyword in keywords)

    def calculate_auto_unit_price(self):
        garment_text = (self.garment_type or '').lower()
        description_text = (self.description or '').lower()
        instructions_text = (self.special_instructions or '').lower()
        combined_text = ' '.join([garment_text, description_text, instructions_text]).strip()

        if self._match_any_keyword(combined_text, ['original jean hem']):
            return Decimal('12.00')
        if self._match_any_keyword(combined_text, ['hemming', 'hem']):
            if self._match_any_keyword(combined_text, ['dress']):
                return Decimal('20.00')
            if self._match_any_keyword(combined_text, ['skirt']):
                return Decimal('15.00')
            if self._match_any_keyword(combined_text, ['jean', 'jeans', 'pants', 'trousers']):
                return Decimal('9.50')
        if self._match_any_keyword(combined_text, ['waist', 'taking in waist', 'letting out waist']):
            return Decimal('14.00')
        if self._match_any_keyword(combined_text, ['zipper', 'zip']):
            if self._match_any_keyword(combined_text, ['dress', 'skirt']):
                return Decimal('20.00')
            return Decimal('12.50')
        if self._match_any_keyword(combined_text, ['sleeve shortening', 'shortening sleeves']):
            if self._match_any_keyword(combined_text, ['jacket', 'coat']):
                return Decimal('20.00')
            return Decimal('12.50')
        if self._match_any_keyword(combined_text, ['taking in sides']):
            if self._match_any_keyword(combined_text, ['jacket', 'coat']):
                return Decimal('32.50')
            if self._match_any_keyword(combined_text, ['dress', 'skirt']):
                return Decimal('25.00')
            return Decimal('11.50')
        if self._match_any_keyword(combined_text, ['replacing lining', 'replace lining', 'lining']):
            return Decimal('52.50')
        if self._match_any_keyword(combined_text, ['collar', 'turning collar', 'replace collar']):
            return Decimal('15.00')
        if self._match_any_keyword(combined_text, ['patch', 'small repair', 'repair']):
            return Decimal('8.50')
        if self._match_any_keyword(combined_text, ['button', 'buttons']):
            return Decimal('2.00')

        if self._match_any_keyword(garment_text, ['wedding gown']):
            return Decimal('65.00')
        if self._match_any_keyword(garment_text, ['suit jacket', 'jacket', 'coat']):
            return Decimal('25.00')
        if self._match_any_keyword(garment_text, ['dress']):
            return Decimal('20.00')
        if self._match_any_keyword(garment_text, ['skirt']):
            return Decimal('15.00')
        if self._match_any_keyword(garment_text, ['shirt', 'blouse']):
            return Decimal('12.00')
        if self._match_any_keyword(garment_text, ['trousers', 'pants', 'jeans']):
            return Decimal('10.00')
        if self._match_any_keyword(garment_text, ['alteration']):
            return Decimal('12.00')

        return Decimal('15.00')

    def save(self, *args, **kwargs):
        # Pricing source-of-truth lives in shop/services/pricing.py.
        # Only auto-fill on first save when no price has been set yet,
        # so that pricing.quote_order() values are never overwritten.
        if self.unit_price in (None, Decimal('0.00')):
            self.unit_price = self.calculate_auto_unit_price()
        super().save(*args, **kwargs)

    @property
    def line_total(self):
        return (self.unit_price * self.quantity) - self.item_discount


class Measurement(models.Model):
    UNIT_CHOICES = [
        ('cm', 'Centimeters'),
        ('in', 'Inches'),
        ('mm', 'Millimeters'),
    ]

    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='measurements')
    measurement_type = models.CharField(max_length=100, help_text='e.g. bust, waist, sleeve_length, inseam')
    measurement_value = models.DecimalField(max_digits=7, decimal_places=2)
    unit = models.CharField(max_length=5, choices=UNIT_CHOICES, default='cm')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['order_item', 'measurement_type']
        verbose_name = 'Measurement'
        verbose_name_plural = 'Measurements'

    def __str__(self):
        return f"{self.measurement_type}: {self.measurement_value} {self.unit} ({self.order_item})"


class WorkTicket(models.Model):
    TICKET_STATUS_CHOICES = [
        ('open', 'Open'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('blocked', 'Blocked'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='tickets')
    current_stage = models.ForeignKey(ProductionStage, on_delete=models.PROTECT,
                                       null=True, blank=True, related_name='active_tickets')
    ticket_code = models.CharField(max_length=50, unique=True, blank=True)
    created_date = models.DateField(default=timezone.now)
    deadline = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=TICKET_STATUS_CHOICES, default='open')
    design_notes = models.TextField(blank=True)
    observations = models.TextField(blank=True)
    attachments = GenericRelation('Attachment', related_query_name='ticket')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Work Ticket'
        verbose_name_plural = 'Work Tickets'

    def __str__(self):
        return f"Ticket {self.ticket_code} — {self.order_item.garment_type} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.ticket_code:
            super().save(*args, **kwargs)
            self.ticket_code = f"TKT-{self.pk:05d}"
            self.save(update_fields=['ticket_code'])
        else:
            super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        if self.deadline and self.status not in ['completed', 'cancelled']:
            return self.deadline < timezone.now().date()
        return False

    @property
    def current_assignee(self):
        assignment = self.assignments.filter(assignment_status='current').first()
        return assignment.employee if assignment else None

    @property
    def qr_payload(self):
        """Computed payload encoded into the ticket's QR. Never stored."""
        return f"CDP-TICKET:{self.ticket_code}"


class TaskAssignment(models.Model):
    ASSIGNMENT_STATUS_CHOICES = [
        ('current', 'Current'),
        ('reassigned', 'Reassigned'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    ticket = models.ForeignKey(WorkTicket, on_delete=models.CASCADE, related_name='assignments')
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='task_assignments')
    assigned_at = models.DateTimeField(default=timezone.now)
    unassigned_at = models.DateTimeField(null=True, blank=True)
    assignment_status = models.CharField(max_length=20, choices=ASSIGNMENT_STATUS_CHOICES, default='current')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = 'Task Assignment'
        verbose_name_plural = 'Task Assignments'

    def __str__(self):
        return f"{self.employee.full_name} → {self.ticket.ticket_code} ({self.get_assignment_status_display()})"


class TicketStatusHistory(models.Model):
    ticket = models.ForeignKey(WorkTicket, on_delete=models.CASCADE, related_name='status_history')
    stage = models.ForeignKey(ProductionStage, on_delete=models.PROTECT, related_name='history_records')
    changed_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='status_changes')
    changed_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name = 'Ticket Status History'
        verbose_name_plural = 'Ticket Status Histories'

    def __str__(self):
        return f"{self.ticket.ticket_code} → {self.stage.stage_name} at {self.changed_at:%Y-%m-%d %H:%M}"


class DamageIncident(models.Model):
    INCIDENT_TYPE_CHOICES = [
        ('ripped', 'Ripped'),
        ('stained', 'Stained'),
        ('wrong_cut', 'Wrong Cut'),
        ('wrong_measurement', 'Wrong Measurement'),
        ('lost_item', 'Lost Item'),
        ('other', 'Other'),
    ]

    SEVERITY_CHOICES = [
        ('minor', 'Minor'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
    ]

    RESOLUTION_CHOICES = [
        ('repair', 'Repair'),
        ('remake', 'Remake'),
        ('discount', 'Discount'),
        ('cancel_item', 'Cancel Item'),
        ('pending', 'Pending Resolution'),
    ]

    ticket = models.ForeignKey(WorkTicket, on_delete=models.CASCADE, related_name='damage_incidents')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='damage_incidents')
    reported_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='reported_incidents')
    incident_date = models.DateField(default=timezone.now)
    incident_type = models.CharField(max_length=25, choices=INCIDENT_TYPE_CHOICES)
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='minor')
    resolution_action = models.CharField(max_length=15, choices=RESOLUTION_CHOICES, default='pending')
    resolution_notes = models.TextField(blank=True)
    internal_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-incident_date']
        verbose_name = 'Damage Incident'
        verbose_name_plural = 'Damage Incidents'

    def __str__(self):
        return f"{self.get_incident_type_display()} on {self.order_item.garment_type} — {self.incident_date}"


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_payment', 'Mobile Payment'),
    ]

    PAYMENT_STAGE_CHOICES = [
        ('advance', 'Advance'),
        ('deposit', 'Deposit'),
        ('partial', 'Partial'),
        ('final', 'Final'),
    ]

    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='payments')
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    payment_stage = models.CharField(max_length=10, choices=PAYMENT_STAGE_CHOICES, default='partial')
    reference_code = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"Payment EUR {self.amount} for Order #{self.order_id} ({self.get_payment_stage_display()})"


class Delivery(models.Model):
    DELIVERY_METHOD_CHOICES = [
        ('pickup', 'Customer Pickup'),
        ('home_delivery', 'Home Delivery'),
        ('courier', 'Courier Service'),
    ]

    order = models.OneToOneField(CustomerOrder, on_delete=models.CASCADE, related_name='delivery')
    delivery_date = models.DateField(default=timezone.now)
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_METHOD_CHOICES, default='pickup')
    received_by = models.CharField(max_length=200, blank=True, help_text='Name of person who received')
    comments = models.TextField(blank=True)
    is_delivered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Delivery'
        verbose_name_plural = 'Deliveries'

    def __str__(self):
        status = "Delivered" if self.is_delivered else "Pending"
        return f"Delivery for Order #{self.order_id} — {status}"


class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True, help_text='ISO 4217 e.g. EUR, USD, GBP')
    name = models.CharField(max_length=80)
    symbol = models.CharField(max_length=8, default='€')
    is_base = models.BooleanField(default=False, help_text='Exactly one row should be the base.')

    class Meta:
        ordering = ['code']
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'

    def __str__(self):
        return f"{self.code} ({self.symbol})"


class ExchangeRate(models.Model):
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE, related_name='rates')
    rate_to_base = models.DecimalField(max_digits=14, decimal_places=6,
        help_text='Multiply an amount in this currency by this value to get the base currency.')
    captured_on = models.DateField(default=timezone.now)
    source = models.CharField(max_length=80, blank=True, default='manual')

    class Meta:
        ordering = ['-captured_on']
        unique_together = ('currency', 'captured_on')
        verbose_name = 'Exchange Rate'
        verbose_name_plural = 'Exchange Rates'

    def __str__(self):
        return f"{self.currency.code} → base: {self.rate_to_base} on {self.captured_on}"


class GarmentCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('15.00'),
        help_text='Base price in EUR before fabric/add-ons/urgency.')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Garment Category'
        verbose_name_plural = 'Garment Categories'

    def __str__(self):
        return f"{self.name} (€{self.base_price})"


class FabricType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'),
        help_text='Multiply the base price by this value (1.00 = no change).')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Fabric Type'
        verbose_name_plural = 'Fabric Types'

    def __str__(self):
        return f"{self.name} (×{self.multiplier})"


class AddOn(models.Model):
    KIND_CHOICES = [
        ('flat', 'Flat amount'),
        ('per_unit', 'Per unit'),
    ]
    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='flat')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Add-on'
        verbose_name_plural = 'Add-ons'

    def __str__(self):
        return f"{self.name} (+€{self.price} {self.get_kind_display()})"


class UrgencySurcharge(models.Model):
    priority = models.CharField(max_length=10, unique=True,
        choices=CustomerOrder.PRIORITY_CHOICES,
        help_text='Matches CustomerOrder.priority.')
    multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['priority']
        verbose_name = 'Urgency Surcharge'
        verbose_name_plural = 'Urgency Surcharges'

    def __str__(self):
        return f"{self.get_priority_display()} (×{self.multiplier})"


class DiscountRule(models.Model):
    KIND_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed amount (EUR)'),
    ]
    code = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default='percentage')
    value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    min_orders = models.PositiveIntegerField(default=0,
        help_text='Customer must already have at least this many delivered orders.')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE,
        null=True, blank=True, related_name='discount_rules',
        help_text='Leave blank for a public code.')
    valid_from = models.DateField(default=timezone.now)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Discount Rule'
        verbose_name_plural = 'Discount Rules'

    def __str__(self):
        return f"{self.code} ({self.get_kind_display()} {self.value})"

    def is_applicable(self, customer, today=None):
        today = today or timezone.now().date()
        if not self.is_active:
            return False
        if self.valid_from and self.valid_from > today:
            return False
        if self.valid_until and self.valid_until < today:
            return False
        if self.customer and self.customer_id != getattr(customer, 'pk', None):
            return False
        if self.min_orders and customer is not None:
            if customer.completed_order_count < self.min_orders:
                return False
        return True


class ReferralCode(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='owned_referral_code')
    code = models.CharField(max_length=20, unique=True)
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'),
        help_text='Discount percent applied to a redeeming new customer order.')
    uses = models.PositiveIntegerField(default=0)
    max_uses = models.PositiveIntegerField(default=0, help_text='0 = unlimited')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Referral Code'
        verbose_name_plural = 'Referral Codes'

    def __str__(self):
        return f"{self.code} → {self.customer.full_name} ({self.uses} uses)"

    def can_be_used(self):
        if not self.is_active:
            return False
        if self.max_uses and self.uses >= self.max_uses:
            return False
        return True


class CustomerReferral(models.Model):
    referrer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='referrals_made')
    referee = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='referrals_received')
    order = models.ForeignKey(CustomerOrder, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='referrals')
    code_used = models.CharField(max_length=20)
    reward_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer Referral'
        verbose_name_plural = 'Customer Referrals'

    def __str__(self):
        return f"{self.referrer} → {self.referee} via {self.code_used}"


# ────────────────────────────────────────────────────────────────────────────
#  Storage locations (physical garment tracking)
# ────────────────────────────────────────────────────────────────────────────


class StorageLocation(models.Model):
    KIND_CHOICES = [
        ('shelf', 'Shelf'),
        ('hanger', 'Hanger'),
        ('bin', 'Bin'),
        ('rail', 'Rail'),
        ('drawer', 'Drawer'),
    ]
    code = models.CharField(max_length=40, unique=True, help_text='Short label e.g. S-A12, H-03')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='shelf')
    area = models.CharField(max_length=80, blank=True, help_text='Workshop zone or room')
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Storage Location'
        verbose_name_plural = 'Storage Locations'

    def __str__(self):
        return f"{self.code} ({self.get_kind_display()})"


# ────────────────────────────────────────────────────────────────────────────
#  Inventory & suppliers
# ────────────────────────────────────────────────────────────────────────────


class Supplier(models.Model):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    lead_time_days = models.PositiveIntegerField(default=7,
        help_text='Typical days from order placed to delivery.')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'

    def __str__(self):
        return self.name


class Material(models.Model):
    CATEGORY_CHOICES = [
        ('fabric', 'Fabric'),
        ('thread', 'Thread'),
        ('zipper', 'Zipper'),
        ('button', 'Button'),
        ('lining', 'Lining'),
        ('trim', 'Trim'),
        ('other', 'Other'),
    ]
    UNIT_CHOICES = [
        ('m', 'Meters'),
        ('cm', 'Centimeters'),
        ('unit', 'Units'),
        ('roll', 'Rolls'),
        ('spool', 'Spools'),
    ]
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='fabric')
    color = models.CharField(max_length=80, blank=True)
    default_unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='m')
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='materials')
    stock_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    location = models.ForeignKey(StorageLocation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='materials')
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Material'
        verbose_name_plural = 'Materials'

    def __str__(self):
        return f"{self.name} ({self.color})" if self.color else self.name

    @property
    def is_low_stock(self):
        return self.stock_on_hand <= self.low_stock_threshold and self.is_active

    @property
    def usage_count(self):
        return self.line_items.count()


class OrderItemMaterial(models.Model):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='materials_used')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='line_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    unit_cost_snapshot = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text='Cost per unit at time of consumption. Frozen.')
    notes = models.CharField(max_length=200, blank=True)
    consumed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-consumed_at']
        verbose_name = 'Material consumption'
        verbose_name_plural = 'Material consumptions'

    def __str__(self):
        return f"{self.material} × {self.quantity} on {self.order_item}"


class MaterialRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('converted', 'Converted to supplier order'),
        ('fulfilled', 'Fulfilled'),
        ('cancelled', 'Cancelled'),
    ]
    PRIORITY_CHOICES = CustomerOrder.PRIORITY_CHOICES

    requested_by = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='material_requests')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='requests')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    reason = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='material_decisions')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)
    supplier_order = models.ForeignKey('SupplierOrder', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_requests',
        help_text='Set when the request is converted to a supplier order.')
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Material Request'
        verbose_name_plural = 'Material Requests'

    def __str__(self):
        return f"{self.requested_by.full_name} → {self.material} × {self.quantity} ({self.get_status_display()})"


class SupplierOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('placed', 'Placed'),
        ('shipped', 'Shipped'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft')
    placed_on = models.DateField(null=True, blank=True)
    expected_on = models.DateField(null=True, blank=True)
    received_on = models.DateField(null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Supplier Order'
        verbose_name_plural = 'Supplier Orders'

    def __str__(self):
        return f"SO #{self.pk} → {self.supplier.name} ({self.get_status_display()})"

    def recalculate_total(self):
        total = self.lines.aggregate(
            t=models.Sum(models.F('quantity') * models.F('unit_cost'),
                          output_field=models.DecimalField(max_digits=14, decimal_places=2))
        )['t'] or Decimal('0.00')
        self.total = total
        self.save(update_fields=['total'])


class SupplierOrderLine(models.Model):
    supplier_order = models.ForeignKey(SupplierOrder, on_delete=models.CASCADE, related_name='lines')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name='supplier_lines')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        verbose_name = 'Supplier order line'
        verbose_name_plural = 'Supplier order lines'

    def __str__(self):
        return f"{self.material} × {self.quantity} @ €{self.unit_cost}"


CHANNEL_CHOICES = [
    ('inapp', 'In-app'),
    ('email', 'Email'),
    ('sms', 'SMS'),
    ('whatsapp', 'WhatsApp'),
]


class NotificationPreference(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_preferences')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'channel')
        verbose_name = 'Notification preference'
        verbose_name_plural = 'Notification preferences'

    def __str__(self):
        return f"{self.user} · {self.get_channel_display()} {'on' if self.enabled else 'off'}"


class NotificationLog(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    event = models.CharField(max_length=80, help_text='Event name from shop/events.py')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    recipient = models.CharField(max_length=200, help_text='Email, phone, or username')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications')
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='queued')
    error = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification log'
        verbose_name_plural = 'Notification log'

    def __str__(self):
        return f"{self.event} → {self.recipient} ({self.channel}, {self.status})"


class Attachment(models.Model):
    KIND_CHOICES = [
        ('reference', 'Reference image'),
        ('progress', 'Progress photo'),
        ('final', 'Final product'),
        ('receipt', 'Receipt'),
        ('intake', 'Intake submission'),
        ('other', 'Other'),
    ]
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey('content_type', 'object_id')
    file = models.FileField(upload_to='attachments/%Y/%m/')
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default='reference')
    caption = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]
        verbose_name = 'Attachment'
        verbose_name_plural = 'Attachments'

    def __str__(self):
        return f"{self.get_kind_display()} on {self.content_type} #{self.object_id}"

class Appointment(models.Model):
    KIND_CHOICES = [
        ('fitting', 'Fitting'),
        ('alteration', 'Alteration'),
        ('pickup', 'Pickup'),
        ('intake', 'Intake consultation'),
    ]
    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No-show'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='appointments')
    order = models.ForeignKey(CustomerOrder, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='appointments')
    kind = models.CharField(max_length=15, choices=KIND_CHOICES, default='fitting')
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    location = models.CharField(max_length=200, blank=True,
        default='Costuras de Paqui · C. de San Enrique 16, Madrid')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='requested')
    notes = models.TextField(blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_at']
        verbose_name = 'Appointment'
        verbose_name_plural = 'Appointments'

    def __str__(self):
        return f"{self.get_kind_display()} · {self.customer.full_name} · {self.scheduled_at:%Y-%m-%d %H:%M}"

class Invoice(models.Model):
    order = models.OneToOneField(CustomerOrder, on_delete=models.CASCADE, related_name='invoice')
    number = models.CharField(max_length=40, unique=True, blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    language = models.CharField(max_length=5, choices=Customer.LANGUAGE_CHOICES, default='es')
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text='Total in the order currency. Frozen at issue time.')
    currency_code = models.CharField(max_length=3, default='EUR')
    pdf_path = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ['-issued_at']
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'

    def __str__(self):
        return f"Invoice {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            super().save(*args, **kwargs)
            self.number = f"INV-{self.issued_at.strftime('%Y%m')}-{self.pk:05d}"
            self.save(update_fields=['number'])
        else:
            super().save(*args, **kwargs)


class Receipt(models.Model):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt')
    number = models.CharField(max_length=40, unique=True, blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    language = models.CharField(max_length=5, choices=Customer.LANGUAGE_CHOICES, default='es')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    currency_code = models.CharField(max_length=3, default='EUR')

    class Meta:
        ordering = ['-issued_at']
        verbose_name = 'Receipt'
        verbose_name_plural = 'Receipts'

    def __str__(self):
        return f"Receipt {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            super().save(*args, **kwargs)
            self.number = f"REC-{self.issued_at.strftime('%Y%m')}-{self.pk:05d}"
            self.save(update_fields=['number'])
        else:
            super().save(*args, **kwargs)

class OrderTemplate(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='order_templates')
    name = models.CharField(max_length=120)
    snapshot = models.JSONField(default=dict,
        help_text='Items + measurements + notes captured from a past order.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Order template'
        verbose_name_plural = 'Order templates'

    def __str__(self):
        return f"{self.name} · {self.customer.full_name}"

class Lead(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('converted', 'Converted'),
        ('rejected', 'Rejected'),
    ]
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    garment_type = models.CharField(max_length=120)
    fabric = models.CharField(max_length=120, blank=True)
    color = models.CharField(max_length=80, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    language = models.CharField(max_length=5, choices=Customer.LANGUAGE_CHOICES, default='es')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='new')
    converted_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_leads')
    converted_order = models.ForeignKey(CustomerOrder, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_leads')
    attachments = GenericRelation('Attachment', related_query_name='lead')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Intake lead'
        verbose_name_plural = 'Intake leads'

    def __str__(self):
        return f"{self.name} · {self.garment_type} · {self.get_status_display()}"

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_actions')
    action = models.CharField(max_length=80,
        help_text='e.g. order.transition, payment.recorded, material.approved')
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=400, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-at']
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['action']),
        ]
        verbose_name = 'Audit log entry'
        verbose_name_plural = 'Audit log'

    def __str__(self):
        return f"{self.action} · {self.target_type}#{self.target_id} · {self.at:%Y-%m-%d %H:%M}"


class OrderEvent(models.Model):
    """Lightweight non-status events on an order (paid, shipped, called, etc.)."""
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-at']
        verbose_name = 'Order event'
        verbose_name_plural = 'Order events'

    def __str__(self):
        return f"#{self.order_id} · {self.kind} · {self.at:%Y-%m-%d %H:%M}"
