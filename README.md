# Costuras de Paqui - Sewing Shop Management System

Django-based management system for sewing shop operations from customer intake to final delivery. The project is built around a relational database and includes Django Unfold integration for the admin and management experience.

## Project Objective

The system supports the full operational flow of a sewing shop:

- customer registration and profile history
- order creation and updates
- garment/item registration per order
- work ticket generation and production tracking
- production stage progression and assignment control
- measurements and material usage recording
- completion, payment, and delivery management
- operational monitoring through dashboards and reports

## Required Technology Stack

- `Django` as the primary backend framework
- relational database support (`SQLite` by default, `PostgreSQL` supported)
- `Django ORM` for schema and relationship management
- `Django Unfold` integrated in admin configuration
- complementary tooling for deployment and environment management

## Functional Modules Implemented

### 1) Customer Management

- register customers with contact data and notes
- maintain customer records
- inspect customer order history

### 2) Order Management

- create and edit orders linked to customers
- track order date, due date, status, and priority
- include multiple garments/items per order
- apply discounts and track payment option/status

### 3) Ticket / Work Order Management

- generate work tickets per garment
- include deadline, priority, stage, and design notes
- assign and reassign employees to tickets
- keep ticket audit logs through status history

### 4) Production Tracking

- move tickets through ordered production stages
- maintain stage history and current status
- detect blocked, active, completed, and overdue work

### 5) Delivery and Completion

- create delivery records and confirm deliveries
- mark orders/items as delivered
- enforce business rule: unresolved damage incidents block delivery

### 6) Reporting and Monitoring

- dashboard metrics for pending, in-production, overdue, completed, delivered
- ticket monitoring by stage, urgency, and blockage
- customer and revenue summaries in reports

## Workflows

The application implements at least the required 3 complete workflows:

1. **Customer Order Creation**
   - staff registers customer
   - creates order
   - adds garment details and due date
   - records measurements

2. **Ticket Creation and Production Follow-up**
   - work ticket created from order item
   - ticket assigned to employee
   - ticket moves through production stages
   - status history captured

3. **Order Completion and Delivery**
   - tickets/items completed
   - order becomes ready for delivery
   - delivery created and confirmed
   - order closed as delivered

Additional implemented workflows include quality incident handling, payment tracking, customer self-service booking, and material usage tracking.

## Relational Database Design

Core entities include:

- `Customer`
- `Employee`, `EmployeeAvailability`
- `CustomerOrder`, `OrderItem`
- `Measurement`
- `WorkTicket`, `TaskAssignment`, `TicketStatusHistory`
- `DamageIncident`
- `Payment`
- `Delivery`
- `Material`, `OrderItemMaterial`
- `ProductionStage`

Design characteristics:

- explicit primary and foreign key relationships
- one-to-many and one-to-one cardinalities aligned with business rules
- normalized structure to avoid redundancy
- schema supports order lifecycle and production traceability

## Quick Start (SQLite)

```bash
cd costuras-de-paqui 
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Access points:

- Customer portal: `http://127.0.0.1:8000/portal/`
- Employee portal: `http://127.0.0.1:8000/staff/login/`
- Staff dashboard: `http://127.0.0.1:8000/dashboard/`
- Django Unfold admin: `http://127.0.0.1:8000/admin/`

Seeded credentials:

- admin: `admin` / `admin123`
- employee example: `carlos.ruiz@stitchpro.com` / `staff123`
- customer example: `isabella@email.com` / `customer123`

## PostgreSQL Configuration (Optional)

Set `.env` values:

```bash
USE_SQLITE=False
DB_NAME=sewingshop_db
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

Then run:

```bash
psql -U postgres -c "CREATE DATABASE sewingshop_db;"
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

The project also supports `DATABASE_URL` for cloud platforms.

## Django Unfold Integration

Unfold is used for:

- grouped admin navigation by domain modules
- improved list/detail management for operations
- status and priority visual badges
- inline management for related entities (items, tickets, payments, incidents, measurements, material usage)

## Suggested Business Rules Covered

- each order belongs to one customer
- an order can contain multiple garments/items
- each garment can have one or more work tickets
- tickets always keep a current status and stage history
- delivered orders record delivery state/date
- due dates and overdue items are monitored
- unresolved damage incidents block delivery confirmation

## Testing

Run project tests with:

```bash
python manage.py test shop
```

## Source Code and Setup Files

Repository includes:

- complete Django source code
- `requirements.txt`
- `.env.example`
- setup and execution instructions
- documentation required for submission

---

## v2: workflow engine, pricing snapshots, multi-currency, intake, and integrations

This release adds the following systems on top of the original codebase. They are
all additive — the original demo data, models, and templates still work.

### Single source of truth for state

All status changes go through `shop/workflow.py`:

```python
from shop import workflow
workflow.transition(order, to='ready_for_delivery', actor=request.user)
workflow.advance_stage(ticket, to_stage=stage, actor=request.user)
workflow.schedule_delivery(order, delivery_date=..., delivery_method='pickup', actor=...)
workflow.confirm_delivery(order, actor=...)
workflow.transition_request(material_request, to='approved', actor=...)
```

The engine also exposes `workflow.next_states(obj)` so UIs render only the
transitions that are currently legal, with a `blocking_reason` when one is
disallowed (for example, "Not all items are completed yet" hides the
"Ready for delivery" button until items finish). A grep test
(`shop.tests.test_no_direct_status_writes`) prevents views from writing
`.status =` directly.

### Frozen pricing snapshots

`shop/services/pricing.py` reads the live pricing tables (`GarmentCategory`,
`FabricType`, `AddOn`, `UrgencySurcharge`, `DiscountRule`, `ReferralCode`) once
at booking time and freezes the result onto the order's `pricing_snapshot`,
`subtotal_amount`, `final_amount`, `base_subtotal`, `base_final`,
`exchange_rate`, and `currency`. Receipts, invoices, customer dashboards, staff
detail pages, and reports all read those frozen fields — never the live tables.
A unit test (`shop.tests.test_pricing_snapshot::test_historical_reads_use_snapshot`)
mutates every live table and asserts that historical totals stay identical.

### Multi-currency

The base currency is EUR (Spain). Other currencies and rates live in `Currency`
and `ExchangeRate`. Convert on the fly with `shop/services/fx.py`. Refresh
rates with:

```bash
python manage.py refresh_rates
```

### Inventory and supplier orders

- `Material` (with `low_stock_threshold` and `usage_count`)
- `Supplier`
- `MaterialRequest` with the lifecycle `pending → approved → converted → fulfilled`
  (or `rejected` / `cancelled`), all governed by `workflow.transition_request`
- `SupplierOrder` + `SupplierOrderLine`
- Convert an approved request into a draft supplier order in one click;
  receiving the supplier order increments stock and auto-fulfills the source
  request

Staff dashboard at `/inventory/` and `/material-requests/`. Employees
self-serve at `/staff/requests/new/`.

### Event-driven notifications

`shop/events.py` defines named events. Subscribers in
`shop/services/communications.py` fan them out to email / SMS / WhatsApp /
in-app channels through pluggable providers. With no API keys configured the
providers print to the console; with `.env` keys they activate Twilio,
Stripe, SMTP, etc. Every notification is recorded in `NotificationLog` and
visible at `/notifications/`.

### Online payments

`/portal/orders/<pk>/pay/` lets a customer pay through:

- the in-app stub form (default), or
- a real Stripe Checkout session if `STRIPE_SECRET_KEY` is set

A webhook endpoint at `/payments/webhook/` ingests Stripe `checkout.session.completed`.

### Public intake form, leads, and conversion

`/intake/` is the public lead form (no login required). Each submission
becomes a `Lead`, fires `events.LEAD_RECEIVED`, and lands at `/leads/` for
staff. One click converts a lead into a Customer + Order with a fresh
pricing snapshot.

### Repeat-order templates and referrals

- "Save template" and "Reorder" buttons appear on completed customer orders
- Templates live at `/portal/dashboard/`
- Each customer auto-gets a referral code (`CDP-XXXXXX`) tracked in
  `ReferralCode` + `CustomerReferral`
- Booking accepts a referral / discount code and applies it via
  `pricing.apply_discount`

### QR codes and scanning

Each `WorkTicket.qr_payload` is a derived property; the staff scan page is at
`/staff/scan/` and accepts both the raw ticket code and the full QR payload
(`CDP-TICKET:TKT-00001`).

### Appointments

`Appointment` records fittings, alterations, pickups, and consultations.
Customers book at `/portal/appointments/`. Reminders are sent via
`events.FITTING_REMINDER`.

### Receipts, invoices, audit log

- Printable invoice: `/orders/<pk>/invoice/?lang=es|en|fr`
- Printable receipt: `/payments/<id>/receipt/?lang=es|en|fr`
- Every state change writes an `AuditLog` row visible per-order on the staff
  detail page and globally in the admin

### Seeding the new tables

Run after the original `seed_data` (idempotent, will not duplicate rows):

```bash
python manage.py seed_extras
```

This adds garment categories, fabric types, add-ons, urgency surcharges,
discount rules, currencies, exchange rates, suppliers, materials, storage
locations, referral codes for existing customers, and one demo lead and
material request.

### Settings reference

See `.env.example` for every key. Anything left blank uses an in-process stub.

