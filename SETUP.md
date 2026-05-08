# Sewing Shop Management System - Setup and Run Guide

## 1. Prerequisites

* **Python 3.10 to 3.14** (3.14 is supported via a compatibility shim, see
  end of this file).
* `pip`
* (optional) **PostgreSQL 13+** for non-SQLite use.

## 2. Clone and create a virtual environment

```bash
cd costuras-de-paqui 
python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# Windows cmd.exe
venv\Scripts\activate.bat
# macOS / Linux
source venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure environment

The repository ships an `.env.example` that already sets `USE_SQLITE=True`
so the project boots with **zero** database setup. Copy it:

```bash
cp .env.example .env       # macOS / Linux
copy .env.example .env     # Windows
```

To use **PostgreSQL** instead, set:

```env
USE_SQLITE=False
DB_NAME=sewingshop_db
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

## 5. Migrations

```bash
python manage.py migrate
```

## 6. Demo data

```bash
python manage.py seed_data
```

This creates the superuser (`admin` / `admin123`), a portal-enabled customer
(`isabella@email.com` / `customer123`), six staff users (all with
`staff123`), the eight production stages and four representative orders
covering: a delivered order, an in-production order, an overdue urgent
order, and a freshly received order.

## 7. Run

```bash
python manage.py runserver
```

Open one of:

| URL                                  | Audience          | Login                                 |
| ------------------------------------ | ----------------- | ------------------------------------- |
| http://127.0.0.1:8000/portal/        | Customers (public)| `isabella@email.com` / `customer123`  |
| http://127.0.0.1:8000/staff/login/   | Employees         | `carlos.ruiz@stitchpro.com` / `staff123` |
| http://127.0.0.1:8000/dashboard/     | Shop staff        | `admin` / `admin123`                  |
| http://127.0.0.1:8000/admin/         | Manager / admin   | `admin` / `admin123`                  |

## 8. Where things live

| Path                                | Purpose                                   |
| ----------------------------------- | ----------------------------------------- |
| `shop/models.py`                    | Database schema (15 domain models)        |
| `shop/views.py`                     | Staff, employee and customer-portal views |
| `shop/admin.py`                     | Django Unfold admin configuration         |
| `shop/forms.py`                     | ModelForms for every workflow             |
| `shop/urls.py`                      | All `/customers/`, `/orders/`, `/tickets/`, `/staff/`, `/portal/` routes |
| `shop/management/commands/seed_data.py` | Demo data loader                      |
| `templates/shop/`                   | Staff dashboard & forms (Bootstrap 5)    |
| `templates/employee/`               | Employee portal                          |
| `templates/portal/`                 | Public customer portal                   |
| `docs/`                             | Submission documents                     |

## 9. Production deployment

The repository is ready for Railway / Heroku-style deployment:

* `Procfile`: `web: gunicorn sewingshop.wsgi --log-file -`
* `railway.toml`: runs `migrate`, `seed_data`, `gunicorn`
* `whitenoise`: serves static files
* `dj-database-url`: auto-picks `DATABASE_URL` for the database

Set:

```env
SECRET_KEY=<generate a long random string>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,*.railway.app
DATABASE_URL=postgres://...
```

then `python manage.py collectstatic --noinput`.

## 10. Notes on Python 3.14

Django 4.2 LTS does not officially support Python 3.14 because
`django.template.context.BaseContext.__copy__` uses `copy(super())`, a
construct that the new `super` proxy in Python 3.14 no longer copies. The
project ships a small compatibility shim in `shop/apps.py` (in
`ShopConfig.ready`) that monkey-patches the method only when running on
Python ≥ 3.14, so the app runs on every Python version from 3.10 through
3.14.

If you prefer a stock environment, run on Python 3.10-3.13.

## 11. Common operations

```bash
# create another superuser
python manage.py createsuperuser

# run the test client against your local install
python manage.py shell

# reset the SQLite database from scratch
rm db.sqlite3
python manage.py migrate
python manage.py seed_data
```
