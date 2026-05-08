# Problem Description

> The full submission documents live in [`docs/`](./docs/):
>
> 1. [Problem Description](./docs/01_problem_description.md)
> 2. [Requirements Description](./docs/02_requirements_description.md)
> 3. [Normalized Database Design](./docs/03_database_design.md)
> 4. [Entity Relationship Diagram](./docs/04_erd.md)
> 5. [Workflow Documentation](./docs/05_workflows.md)
> 6. [Change Log](./docs/06_changelog.md)
>
> Setup and run instructions live in [`README.md`](./README.md) and
> [`SETUP.md`](./SETUP.md).

## Quick summary

"Costuras de Paqui" is a small bespoke sewing shop that trades as
**StitchPro** in the application. The shop needs a single relational
system to manage its daily operations end to end. The system should
cover:

* registering customers and storing their preferences and history;
* recording orders with date, due date, priority and payment option,
  where each order has one or more garments;
* capturing measurements per garment;
* generating production tickets per garment and walking each ticket
  through ordered production stages from order received, through design
  confirmed, cutting, sewing, finishing and quality check, all the way
  to ready for delivery and finally delivered;
* assigning tickets to employees;
* auditing every stage transition;
* handling damage and rework incidents;
* recording payments and reconciling them against the order total;
* scheduling and confirming deliveries;
* monitoring overdue, in progress and completed work for managers,
  employees and customers.

The system is implemented with **Django**, the **Django ORM** and
**Django Unfold** for the admin experience, and it is backed by a
**PostgreSQL** relational database, with a **SQLite** fallback for local
work. See `docs/01_problem_description.md` for the full description.
