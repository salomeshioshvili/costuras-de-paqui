from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_orders(self):
        return self.orders.count()

    @property
    def active_orders(self):
        return self.orders.exclude(status__in=['delivered', 'cancelled']).count()


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
    payment_option = models.CharField(max_length=20, choices=PAYMENT_OPTION_CHOICES, default='full_on_delivery')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    notes = models.TextField(blank=True)
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
        subtotal = self.items.aggregate(
            total=models.Sum(models.F('unit_price') * models.F('quantity'))
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Order Item'
        verbose_name_plural = 'Order Items'

    def __str__(self):
        return f"{self.garment_type} (Order #{self.order_id}) — {self.get_item_status_display()}"

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
        return f"Payment ${self.amount} for Order #{self.order_id} ({self.get_payment_stage_display()})"


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
