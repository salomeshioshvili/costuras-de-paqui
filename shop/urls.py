from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),

    # Customers
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/new/', views.customer_create, name='customer_create'),
    path('customers/<int:pk>/', views.customer_detail, name='customer_detail'),
    path('customers/<int:pk>/edit/', views.customer_edit, name='customer_edit'),

    # Orders
    path('orders/', views.order_list, name='order_list'),
    path('orders/new/', views.order_create, name='order_create'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/edit/', views.order_edit, name='order_edit'),
    path('orders/<int:pk>/status/', views.order_status_update, name='order_status_update'),

    # Order Items
    path('orders/<int:order_pk>/items/add/', views.orderitem_create, name='orderitem_create'),
    path('items/<int:pk>/edit/', views.orderitem_edit, name='orderitem_edit'),
    path('items/<int:item_pk>/measurements/add/', views.measurement_add, name='measurement_add'),

    # Work Tickets
    path('tickets/', views.ticket_list, name='ticket_list'),
    path('tickets/new/', views.ticket_create, name='ticket_create'),
    path('tickets/new/<int:item_pk>/', views.ticket_create, name='ticket_create_for_item'),
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),
    path('tickets/<int:pk>/update-stage/', views.ticket_update_stage, name='ticket_update_stage'),
    path('tickets/<int:pk>/assign/', views.ticket_assign, name='ticket_assign'),

    # Damage Incidents
    path('tickets/<int:ticket_pk>/damage/', views.damage_incident_create, name='damage_incident_create'),
    path('incidents/<int:pk>/resolve/', views.damage_incident_resolve, name='damage_incident_resolve'),

    # Payments
    path('orders/<int:order_pk>/payments/add/', views.payment_add, name='payment_add'),

    # Delivery
    path('orders/<int:order_pk>/delivery/new/', views.delivery_create, name='delivery_create'),
    path('orders/<int:order_pk>/delivery/confirm/', views.delivery_confirm, name='delivery_confirm'),

    # Reports
    path('reports/', views.report_view, name='reports'),

    # Employees
    path('employees/', views.employee_list, name='employee_list'),

    # ── Employee Portal ──────────────────────────────────────────────────────
    path('staff/login/', views.emp_login, name='emp_login'),
    path('staff/logout/', views.emp_logout, name='emp_logout'),
    path('staff/dashboard/', views.emp_dashboard, name='emp_dashboard'),
    path('staff/my-tickets/', views.emp_my_tickets, name='emp_my_tickets'),
    path('staff/tickets/', views.emp_all_tickets, name='emp_all_tickets'),
    path('staff/tickets/<int:pk>/', views.emp_ticket_detail, name='emp_ticket_detail'),
    path('staff/tickets/<int:pk>/update-stage/', views.emp_update_stage, name='emp_update_stage'),
    path('staff/tickets/<int:pk>/complete/', views.emp_complete_ticket, name='emp_complete_ticket'),
    path('staff/orders/', views.emp_orders, name='emp_orders'),
    path('staff/profile/', views.emp_profile, name='emp_profile'),

    # ── Customer Portal ──────────────────────────────────────────────────────
    path('portal/', views.portal_home, name='portal_home'),
    path('portal/register/', views.portal_register, name='portal_register'),
    path('portal/login/', views.portal_login, name='portal_login'),
    path('portal/logout/', views.portal_logout, name='portal_logout'),
    path('portal/dashboard/', views.portal_dashboard, name='portal_dashboard'),
    path('portal/book/', views.portal_book, name='portal_book'),
    path('portal/orders/<int:pk>/', views.portal_order_detail, name='portal_order_detail'),
    path('portal/profile/', views.portal_profile, name='portal_profile'),
]
