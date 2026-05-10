"""
Django settings for sewingshop project.
"""

from pathlib import Path
from decouple import config
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production-please-use-env')

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

INSTALLED_APPS = [
    # Django Unfold must come before django.contrib.admin
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Project app
    'shop.apps.ShopConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sewingshop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'shop.context_processors.role_and_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'sewingshop.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='sewingshop_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# SQLite fallback for development without PostgreSQL
if config('USE_SQLITE', default=False, cast=bool):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Railway / production: DATABASE_URL overrides everything
DATABASE_URL = config('DATABASE_URL', default='')
if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

# Allow Railway-generated domains automatically
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])
RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL', '')
if RAILWAY_STATIC_URL:
    ALLOWED_HOSTS += ['*']  # Railway handles SSL termination

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = config('LANGUAGE_CODE', default='en')
TIME_ZONE = config('TIME_ZONE', default='Europe/Madrid')
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('es', 'Español'),
    ('en', 'English'),
    ('fr', 'Français'),
]

LOCALE_PATHS = [BASE_DIR / 'locale']

APPOINTMENT_MIN_DAYS_AHEAD = 1
APPOINTMENT_ALLOWED_WEEKDAYS = (0, 1, 2, 3, 4)
APPOINTMENT_START_HOUR = 9
APPOINTMENT_END_HOUR_EXCLUSIVE = 18

BOOKING_MIN_DAYS_AHEAD = 1

# ─── Provider configuration (all optional; missing keys → console stub) ────
SMTP_HOST = config('SMTP_HOST', default='')
EMAIL_HOST = SMTP_HOST
EMAIL_PORT = config('SMTP_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('SMTP_USER', default='')
EMAIL_HOST_PASSWORD = config('SMTP_PASSWORD', default='')
EMAIL_USE_TLS = config('SMTP_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@costurasdepaqui.es')
EMAIL_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend' if SMTP_HOST
    else 'django.core.mail.backends.console.EmailBackend'
)

TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER = config('TWILIO_FROM_NUMBER', default='')
TWILIO_WHATSAPP_FROM = config('TWILIO_WHATSAPP_FROM', default='')

STRIPE_SECRET_KEY = config('STRIPE_SECRET_KEY', default='')
STRIPE_PUBLIC_KEY = config('STRIPE_PUBLIC_KEY', default='')
STRIPE_WEBHOOK_SECRET = config('STRIPE_WEBHOOK_SECRET', default='')

EXCHANGE_RATE_API_URL = config('EXCHANGE_RATE_API_URL', default='')

# ─── Cache (FX cache + small per-view caches) ────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'sewingshop',
    }
}

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# In tests we avoid failing manifest lookups when collectstatic has not run,
# so we use non-manifest static storage while tests run.
import sys as _sys
if 'test' in _sys.argv:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# ─── Django Unfold Configuration ──────────────────────────────────────────────
UNFOLD = {
    "SITE_TITLE": "Costuras de Paqui — Admin",
    "SITE_HEADER": "Costuras de Paqui",
    "SITE_SYMBOL": "content_cut",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Operations",
                "separator": True,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": "/admin/",
                    },
                    {
                        "title": "Customers",
                        "icon": "person",
                        "link": "/admin/shop/customer/",
                    },
                    {
                        "title": "Orders",
                        "icon": "shopping_bag",
                        "link": "/admin/shop/customerorder/",
                    },
                    {
                        "title": "Order lines",
                        "icon": "checkroom",
                        "link": "/admin/shop/orderitem/",
                    },
                    {
                        "title": "Work tickets",
                        "icon": "receipt_long",
                        "link": "/admin/shop/workticket/",
                    },
                ],
            },
            {
                "title": "Production",
                "separator": True,
                "items": [
                    {
                        "title": "Stages",
                        "icon": "account_tree",
                        "link": "/admin/shop/productionstage/",
                    },
                    {
                        "title": "Assignments",
                        "icon": "assignment_ind",
                        "link": "/admin/shop/taskassignment/",
                    },
                    {
                        "title": "Stage history",
                        "icon": "history",
                        "link": "/admin/shop/ticketstatushistory/",
                    },
                    {
                        "title": "Incidents",
                        "icon": "report_problem",
                        "link": "/admin/shop/damageincident/",
                    },
                ],
            },
            {
                "title": "Payments & delivery",
                "separator": True,
                "items": [
                    {
                        "title": "Payments",
                        "icon": "payments",
                        "link": "/admin/shop/payment/",
                    },
                    {
                        "title": "Deliveries",
                        "icon": "local_shipping",
                        "link": "/admin/shop/delivery/",
                    },
                ],
            },
            {
                "title": "Team",
                "separator": True,
                "items": [
                    {
                        "title": "Employees",
                        "icon": "group",
                        "link": "/admin/shop/employee/",
                    },
                    {
                        "title": "Availability",
                        "icon": "event_available",
                        "link": "/admin/shop/employeeavailability/",
                    },
                ],
            },
            {
                "title": "Pricing & FX",
                "separator": True,
                "items": [
                    {"title": "Garment categories", "icon": "category",
                     "link": "/admin/shop/garmentcategory/"},
                    {"title": "Fabric types", "icon": "texture",
                     "link": "/admin/shop/fabrictype/"},
                    {"title": "Add-ons", "icon": "add_circle",
                     "link": "/admin/shop/addon/"},
                    {"title": "Urgency surcharges", "icon": "bolt",
                     "link": "/admin/shop/urgencysurcharge/"},
                    {"title": "Discount rules", "icon": "local_offer",
                     "link": "/admin/shop/discountrule/"},
                    {"title": "Currencies", "icon": "euro",
                     "link": "/admin/shop/currency/"},
                    {"title": "Exchange rates", "icon": "currency_exchange",
                     "link": "/admin/shop/exchangerate/"},
                ],
            },
            {
                "title": "Inventory & suppliers",
                "separator": True,
                "items": [
                    {"title": "Materials", "icon": "inventory",
                     "link": "/admin/shop/material/"},
                    {"title": "Material requests", "icon": "request_quote",
                     "link": "/admin/shop/materialrequest/"},
                    {"title": "Suppliers", "icon": "store",
                     "link": "/admin/shop/supplier/"},
                    {"title": "Supplier orders", "icon": "local_mall",
                     "link": "/admin/shop/supplierorder/"},
                    {"title": "Storage locations", "icon": "warehouse",
                     "link": "/admin/shop/storagelocation/"},
                ],
            },
            {
                "title": "Customer experience",
                "separator": True,
                "items": [
                    {"title": "Appointments", "icon": "event",
                     "link": "/admin/shop/appointment/"},
                    {"title": "Intake leads", "icon": "inbox",
                     "link": "/admin/shop/lead/"},
                    {"title": "Order templates", "icon": "list_alt",
                     "link": "/admin/shop/ordertemplate/"},
                    {"title": "Referral codes", "icon": "loyalty",
                     "link": "/admin/shop/referralcode/"},
                    {"title": "Notification log", "icon": "notifications",
                     "link": "/admin/shop/notificationlog/"},
                ],
            },
            {
                "title": "System",
                "separator": True,
                "items": [
                    {"title": "Users", "icon": "manage_accounts",
                     "link": "/admin/auth/user/"},
                    {"title": "Audit log", "icon": "policy",
                     "link": "/admin/shop/auditlog/"},
                ],
            },
        ],
    },
}
