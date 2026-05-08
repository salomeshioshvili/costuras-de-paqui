from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import Sum, Count, Q
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import display, action

from .models import (
    Customer, Employee, EmployeeAvailability,
    ProductionStage, CustomerOrder, OrderItem,
    Measurement, WorkTicket, TaskAssignment,
    TicketStatusHistory, DamageIncident, Payment, Delivery,
    Material, OrderItemMaterial
)



class MeasurementInline(TabularInline):
    model = Measurement
    extra = 2
    fields = ('measurement_type', 'measurement_value', 'unit', 'notes')


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 1
    fields = ('garment_type', 'fabric', 'color', 'size_label', 'quantity', 'unit_price',
              'item_discount', 'item_status', 'special_instructions')
    show_change_link = True


class WorkTicketInline(TabularInline):
    model = WorkTicket
    extra = 0
    fields = ('ticket_code', 'priority', 'status', 'current_stage', 'deadline')
    readonly_fields = ('ticket_code',)
    show_change_link = True


class OrderItemMaterialInline(TabularInline):
    model = OrderItemMaterial
    extra = 1
    fields = ('material', 'quantity', 'unit', 'color_override', 'notes')
    autocomplete_fields = ['material']


class TaskAssignmentInline(TabularInline):
    model = TaskAssignment
    extra = 1
    fields = ('employee', 'assigned_at', 'assignment_status', 'notes')


class TicketStatusHistoryInline(TabularInline):
    model = TicketStatusHistory
    extra = 1
    fields = ('stage', 'changed_by', 'changed_at', 'comment')
    readonly_fields = ('changed_at',)


class DamageIncidentInline(TabularInline):
    model = DamageIncident
    extra = 0
    fields = ('incident_type', 'severity', 'resolution_action', 'is_resolved', 'discount_applied')
    show_change_link = True


class PaymentInline(TabularInline):
    model = Payment
    extra = 1
    fields = ('payment_date', 'amount', 'payment_method', 'payment_stage', 'reference_code')


class AvailabilityInline(TabularInline):
    model = EmployeeAvailability
    extra = 1
    fields = ('date', 'status', 'start_time', 'end_time', 'notes')


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ('full_name', 'phone', 'email', 'display_total_orders',
                    'display_active_orders', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    ordering = ('last_name', 'first_name')
    fieldsets = (
        ('Personal Information', {
            'fields': (('first_name', 'last_name'), ('phone', 'email'), 'address')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
    )

    @display(description='Total Orders')
    def display_total_orders(self, obj):
        return obj.total_orders

    @display(description='Active Orders')
    def display_active_orders(self, obj):
        count = obj.active_orders
        if count > 0:
            return format_html('<span style="color: #7c3aed; font-weight: bold;">{}</span>', count)
        return count


@admin.register(Employee)
class EmployeeAdmin(ModelAdmin):
    list_display = ('full_name', 'role_badge', 'specialty', 'phone', 'is_active',
                    'hire_date', 'display_assignments')
    list_filter = ('role', 'is_active')
    search_fields = ('first_name', 'last_name', 'email', 'specialty')
    inlines = [AvailabilityInline]
    fieldsets = (
        ('Personal Information', {
            'fields': (('first_name', 'last_name'), ('phone', 'email'))
        }),
        ('Work Details', {
            'fields': (('role', 'specialty'), ('hire_date', 'is_active'), 'user')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
    )

    @display(description='Role')
    def role_badge(self, obj):
        colors = {
            'manager': '#7c3aed',
            'tailor': '#059669',
            'cutter': '#d97706',
            'finisher': '#0284c7',
            'quality_control': '#dc2626',
            'receptionist': '#6b7280',
        }
        color = colors.get(obj.role, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">{}</span>',
            color, obj.get_role_display()
        )

    @display(description='Active Tasks')
    def display_assignments(self, obj):
        return obj.current_assignments


@admin.register(EmployeeAvailability)
class EmployeeAvailabilityAdmin(ModelAdmin):
    list_display = ('employee', 'date', 'status', 'start_time', 'end_time')
    list_filter = ('status', 'date', 'employee')
    search_fields = ('employee__first_name', 'employee__last_name')
    date_hierarchy = 'date'


@admin.register(ProductionStage)
class ProductionStageAdmin(ModelAdmin):
    list_display = ('stage_order', 'stage_name', 'description', 'display_active_tickets')
    ordering = ('stage_order',)

    @display(description='Active Tickets')
    def display_active_tickets(self, obj):
        count = obj.active_tickets.exclude(status__in=['completed', 'cancelled']).count()
        if count > 0:
            return format_html('<strong>{}</strong>', count)
        return 0


@admin.register(CustomerOrder)
class CustomerOrderAdmin(ModelAdmin):
    list_display = ('id', 'customer', 'order_date', 'due_date', 'status_badge',
                    'priority_badge', 'final_amount', 'payment_status_badge', 'overdue_flag')
    list_filter = ('status', 'priority', 'payment_status', 'order_date')
    search_fields = ('customer__first_name', 'customer__last_name', 'notes')
    date_hierarchy = 'order_date'
    inlines = [OrderItemInline, PaymentInline]
    autocomplete_fields = ['customer']
    readonly_fields = ('subtotal_amount', 'final_amount', 'created_at', 'updated_at')
    fieldsets = (
        ('Order Details', {
            'fields': ('customer', ('order_date', 'due_date'), ('status', 'priority'), 'notes')
        }),
        ('Financial', {
            'fields': (('subtotal_amount', 'final_amount'),
                       ('order_discount_type', 'order_discount_value'),
                       ('payment_option', 'payment_status'))
        }),
        ('Meta', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @display(description='Status')
    def status_badge(self, obj):
        colors = {
            'draft': '#6b7280',
            'received': '#0284c7',
            'in_production': '#d97706',
            'completed': '#059669',
            'ready_for_delivery': '#7c3aed',
            'delivered': '#16a34a',
            'cancelled': '#dc2626',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">{}</span>',
            color, obj.get_status_display()
        )

    @display(description='Priority')
    def priority_badge(self, obj):
        colors = {'low': '#6b7280', 'normal': '#0284c7', 'high': '#d97706', 'urgent': '#dc2626'}
        color = colors.get(obj.priority, '#6b7280')
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            color, obj.get_priority_display()
        )

    @display(description='Payment')
    def payment_status_badge(self, obj):
        colors = {
            'unpaid': '#dc2626',
            'partially_paid': '#d97706',
            'paid': '#059669',
            'refunded': '#7c3aed',
            'waived': '#6b7280',
        }
        color = colors.get(obj.payment_status, '#6b7280')
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            color, obj.get_payment_status_display()
        )

    @display(description='Overdue')
    def overdue_flag(self, obj):
        if obj.is_overdue:
            return format_html(
                '<span style="color:#dc2626;font-weight:bold">Overdue</span>'
            )
        return 'On time'

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OrderItem)
class OrderItemAdmin(ModelAdmin):
    list_display = ('garment_type', 'order', 'fabric', 'color', 'quantity',
                    'unit_price', 'item_status_badge')
    list_filter = ('item_status', 'garment_type')
    search_fields = ('garment_type', 'description', 'order__customer__first_name',
                     'order__customer__last_name')
    inlines = [MeasurementInline, OrderItemMaterialInline, WorkTicketInline, DamageIncidentInline]

    @display(description='Status')
    def item_status_badge(self, obj):
        colors = {
            'pending': '#6b7280',
            'in_progress': '#d97706',
            'completed': '#059669',
            'damaged': '#dc2626',
            'remake_required': '#7c3aed',
            'cancelled': '#dc2626',
            'delivered': '#16a34a',
        }
        color = colors.get(obj.item_status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">{}</span>',
            color, obj.get_item_status_display()
        )


@admin.register(Measurement)
class MeasurementAdmin(ModelAdmin):
    list_display = ('measurement_type', 'measurement_value', 'unit', 'order_item')
    list_filter = ('unit', 'measurement_type')
    search_fields = ('measurement_type', 'order_item__garment_type')


@admin.register(WorkTicket)
class WorkTicketAdmin(ModelAdmin):
    list_display = ('ticket_code', 'garment_info', 'current_stage', 'status_badge',
                    'priority_badge', 'current_assignee_name', 'deadline', 'overdue_flag')
    list_filter = ('status', 'priority', 'current_stage')
    search_fields = ('ticket_code', 'order_item__garment_type',
                     'order_item__order__customer__first_name',
                     'order_item__order__customer__last_name')
    readonly_fields = ('ticket_code', 'created_at', 'updated_at')
    inlines = [TaskAssignmentInline, TicketStatusHistoryInline, DamageIncidentInline]
    fieldsets = (
        ('Ticket Info', {
            'fields': ('ticket_code', 'order_item', ('current_stage', 'status'), ('priority', 'deadline'))
        }),
        ('Notes', {
            'fields': ('design_notes', 'observations')
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @display(description='Garment')
    def garment_info(self, obj):
        return f"{obj.order_item.garment_type} (Order #{obj.order_item.order_id})"

    @display(description='Status')
    def status_badge(self, obj):
        colors = {
            'open': '#6b7280',
            'assigned': '#0284c7',
            'in_progress': '#d97706',
            'blocked': '#dc2626',
            'completed': '#059669',
            'cancelled': '#6b7280',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">{}</span>',
            color, obj.get_status_display()
        )

    @display(description='Priority')
    def priority_badge(self, obj):
        colors = {'low': '#6b7280', 'normal': '#0284c7', 'high': '#d97706', 'urgent': '#dc2626'}
        color = colors.get(obj.priority, '#6b7280')
        return format_html('<span style="color:{};font-weight:bold">{}</span>',
                           color, obj.get_priority_display())

    @display(description='Assigned To')
    def current_assignee_name(self, obj):
        assignee = obj.current_assignee
        return assignee.full_name if assignee else 'Unassigned'

    @display(description='Overdue')
    def overdue_flag(self, obj):
        if obj.is_overdue:
            return format_html(
                '<span style="color:#dc2626;font-weight:bold">Overdue</span>'
            )
        return 'On time'


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(ModelAdmin):
    list_display = ('ticket', 'employee', 'assignment_status', 'assigned_at', 'unassigned_at')
    list_filter = ('assignment_status', 'employee__role')
    search_fields = ('ticket__ticket_code', 'employee__first_name', 'employee__last_name')


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(ModelAdmin):
    list_display = ('ticket', 'stage', 'changed_by', 'changed_at', 'comment_preview')
    list_filter = ('stage', 'changed_at')
    search_fields = ('ticket__ticket_code', 'comment')
    readonly_fields = ('changed_at',)
    date_hierarchy = 'changed_at'

    @display(description='Comment')
    def comment_preview(self, obj):
        return obj.comment[:60] + '…' if len(obj.comment) > 60 else obj.comment


@admin.register(DamageIncident)
class DamageIncidentAdmin(ModelAdmin):
    list_display = ('order_item', 'incident_type_badge', 'severity_badge', 'resolution_action',
                    'is_resolved', 'reported_by', 'incident_date')
    list_filter = ('incident_type', 'severity', 'resolution_action', 'is_resolved')
    search_fields = ('order_item__garment_type', 'description')
    date_hierarchy = 'incident_date'

    @display(description='Type')
    def incident_type_badge(self, obj):
        return format_html(
            '<span style="color:#dc2626;font-weight:bold">{}</span>',
            obj.get_incident_type_display()
        )

    @display(description='Severity')
    def severity_badge(self, obj):
        colors = {'minor': '#d97706', 'moderate': '#ea580c', 'severe': '#dc2626'}
        color = colors.get(obj.severity, '#6b7280')
        return format_html('<span style="color:{};font-weight:bold">{}</span>',
                           color, obj.get_severity_display())


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ('order', 'payment_date', 'amount', 'payment_method', 'payment_stage', 'reference_code')
    list_filter = ('payment_method', 'payment_stage', 'payment_date')
    search_fields = ('order__customer__first_name', 'order__customer__last_name', 'reference_code')
    date_hierarchy = 'payment_date'


@admin.register(Delivery)
class DeliveryAdmin(ModelAdmin):
    list_display = ('order', 'delivery_date', 'delivery_method', 'received_by', 'is_delivered')
    list_filter = ('delivery_method', 'is_delivered', 'delivery_date')
    search_fields = ('order__customer__first_name', 'order__customer__last_name', 'received_by')
    date_hierarchy = 'delivery_date'


@admin.register(Material)
class MaterialAdmin(ModelAdmin):
    list_display = ('name', 'category_badge', 'color', 'default_unit',
                    'unit_cost', 'supplier', 'is_active', 'usage_count')
    list_filter = ('category', 'is_active', 'default_unit')
    search_fields = ('name', 'color', 'supplier', 'notes')
    fieldsets = (
        ('Material', {
            'fields': (('name', 'category'), ('color', 'default_unit'), 'supplier')
        }),
        ('Pricing & Status', {
            'fields': (('unit_cost', 'is_active'),)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
    )

    @display(description='Category')
    def category_badge(self, obj):
        colors = {
            'fabric': '#7c3aed',
            'thread': '#0284c7',
            'button': '#d97706',
            'lining': '#6b7280',
            'zipper': '#059669',
            'trim': '#db2777',
            'accessory': '#ea580c',
            'other': '#475569',
        }
        color = colors.get(obj.category, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px">{}</span>',
            color, obj.get_category_display()
        )

    @display(description='Used in')
    def usage_count(self, obj):
        c = obj.usage_records.count()
        return f"{c} garment(s)"


@admin.register(OrderItemMaterial)
class OrderItemMaterialAdmin(ModelAdmin):
    list_display = ('material', 'order_item', 'quantity', 'unit', 'effective_color_display', 'created_at')
    list_filter = ('material__category', 'unit')
    search_fields = ('material__name', 'order_item__garment_type',
                     'order_item__order__customer__first_name',
                     'order_item__order__customer__last_name')
    autocomplete_fields = ['material', 'order_item']

    @display(description='Color')
    def effective_color_display(self, obj):
        return obj.effective_color or 'not set'
