"""Inject role + feature flags + topbar counters into every template."""
from django.conf import settings
from django.db.models import Q

from shop.models import Currency, Customer, Employee, Lead, MaterialRequest, NotificationLog
from shop.services.display_currency import resolve_display_currency_code


def role_and_flags(request):
    user = request.user
    is_authenticated = bool(user.is_authenticated)
    is_staff = bool(is_authenticated and user.is_staff)
    is_employee = False
    customer = None
    if is_authenticated:
        is_employee = Employee.objects.filter(user=user).exists()
        customer = Customer.objects.filter(user=user).first()

    notif_unread = 0
    if is_authenticated:
        notif_unread = NotificationLog.objects.filter(
            Q(user=user) | Q(channel='inapp', recipient=user.username),
            is_read=False,
        ).count()

    pending_leads = pending_material_requests = 0
    if is_staff:
        pending_leads = Lead.objects.filter(status='new').count()
        pending_material_requests = MaterialRequest.objects.filter(status='pending').count()

    display_currency_code = resolve_display_currency_code(request)
    display_currency_options = list(
        Currency.objects.order_by('code').values_list('code', flat=True)
    )
    if not display_currency_options:
        display_currency_options = ['EUR']

    flags = {
        'payments_live': bool(getattr(settings, 'STRIPE_SECRET_KEY', '')),
        'sms_live': bool(getattr(settings, 'TWILIO_ACCOUNT_SID', '')),
        'whatsapp_live': bool(getattr(settings, 'TWILIO_WHATSAPP_FROM', '')),
        'email_live': bool(getattr(settings, 'SMTP_HOST', '')),
        'fx_live': bool(getattr(settings, 'EXCHANGE_RATE_API_URL', '')),
    }
    return {
        'role_is_staff': is_staff,
        'role_is_employee': is_employee,
        'role_is_customer': bool(customer),
        'current_customer': customer,
        'feature_flags': flags,
        'topbar_notif_unread': notif_unread,
        'topbar_pending_leads': pending_leads,
        'topbar_pending_requests': pending_material_requests,
        'display_currency_code': display_currency_code,
        'display_currency_options': display_currency_options,
    }
