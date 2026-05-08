from django import forms
from django.utils import timezone
from .models import (
    Customer, CustomerOrder, OrderItem, Measurement,
    WorkTicket, TaskAssignment, TicketStatusHistory,
    DamageIncident, Payment, Delivery, Employee
)


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['first_name', 'last_name', 'phone', 'email', 'address', 'notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 555 0000'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CustomerOrderForm(forms.ModelForm):
    class Meta:
        model = CustomerOrder
        fields = ['customer', 'due_date', 'priority', 'payment_option',
                  'order_discount_type', 'order_discount_value', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'payment_option': forms.Select(attrs={'class': 'form-select'}),
            'order_discount_type': forms.Select(attrs={'class': 'form-select'}),
            'order_discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['garment_type', 'description', 'fabric', 'color', 'size_label',
                  'quantity', 'item_discount', 'special_instructions']
        widgets = {
            'garment_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Dress, Suit'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'fabric': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Cotton, Silk'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Navy Blue'}),
            'size_label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. M, 42, Custom'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'item_discount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'special_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class MeasurementForm(forms.ModelForm):
    class Meta:
        model = Measurement
        fields = ['measurement_type', 'measurement_value', 'unit', 'notes']
        widgets = {
            'measurement_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. bust, waist'}),
            'measurement_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
        }


class WorkTicketForm(forms.ModelForm):
    class Meta:
        model = WorkTicket
        fields = ['order_item', 'current_stage', 'priority', 'deadline', 'design_notes', 'observations']
        widgets = {
            'order_item': forms.Select(attrs={'class': 'form-select'}),
            'current_stage': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'design_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class TicketStatusUpdateForm(forms.Form):
    stage = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='New Production Stage'
    )
    status = forms.ChoiceField(
        choices=WorkTicket.TICKET_STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ticket Status'
    )
    changed_by = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Updated By',
        required=False
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False,
        label='Comment'
    )

    def __init__(self, *args, **kwargs):
        from .models import ProductionStage
        super().__init__(*args, **kwargs)
        self.fields['stage'].queryset = ProductionStage.objects.all()


class TaskAssignmentForm(forms.ModelForm):
    class Meta:
        model = TaskAssignment
        fields = ['employee', 'notes']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].queryset = Employee.objects.filter(is_active=True)


class DamageIncidentForm(forms.ModelForm):
    class Meta:
        model = DamageIncident
        fields = ['incident_type', 'description', 'severity', 'resolution_action',
                  'resolution_notes', 'internal_cost', 'discount_applied', 'is_resolved', 'reported_by']
        widgets = {
            'incident_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'severity': forms.Select(attrs={'class': 'form-select'}),
            'resolution_action': forms.Select(attrs={'class': 'form-select'}),
            'resolution_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'internal_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'discount_applied': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'reported_by': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reported_by'].queryset = Employee.objects.filter(is_active=True)
        self.fields['reported_by'].required = False


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['payment_date', 'amount', 'payment_method', 'payment_stage', 'reference_code', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_stage': forms.Select(attrs={'class': 'form-select'}),
            'reference_code': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['delivery_date', 'delivery_method', 'received_by', 'comments', 'is_delivered']
        widgets = {
            'delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'delivery_method': forms.Select(attrs={'class': 'form-select'}),
            'received_by': forms.TextInput(attrs={'class': 'form-control'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
