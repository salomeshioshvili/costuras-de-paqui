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

See database and ERD documentation in `docs/`.

## Project Documentation (Deliverables)

All required submission documents are available in `docs/`:

1. `01_problem_description.md`
2. `02_requirements_description.md`
3. `03_database_design.md`
4. `04_erd.md`
5. `05_workflows.md`
6. `06_changelog.md`

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
