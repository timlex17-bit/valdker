"""
Django settings for mypos project.
Django 5.x
Production-ready for Render + Local development (Cloudinary + DRF + Jazzmin).
"""

from pathlib import Path
import os
from corsheaders.defaults import default_headers

# --------------------------------------------------
# Load .env file (safe for local, ignored on Render)
# --------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# Core settings
# --------------------------------------------------
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-key"
)

DEBUG = os.environ.get("DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "192.168.1.101",
    "192.168.1.102",
    "192.168.1.197",
    "valdker.onrender.com",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.1.197:5173",
    "https://valdker-vue-js.vercel.app",
    "https://valdker.onrender.com",
]

# --------------------------------------------------
# Applications
# --------------------------------------------------
INSTALLED_APPS = [
    "jazzmin",
    "pos",

    # Cloudinary
    "cloudinary",
    "cloudinary_storage",

    # Third party
    "corsheaders",
    "rest_framework",
    "django_extensions",
    "rest_framework.authtoken",

    # Django default
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# --------------------------------------------------
# DRF settings (Token Auth)
# --------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --------------------------------------------------
# Middleware
# --------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    # CORS must be placed before CommonMiddleware
    "corsheaders.middleware.CorsMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mypos.urls"
WSGI_APPLICATION = "mypos.wsgi.application"
AUTH_USER_MODEL = "pos.CustomUser"

# --------------------------------------------------
# CORS configuration
# --------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    "https://valdker-vue-js.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.1.197:5173",
]

# Allow any Vercel preview subdomain
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https:\/\/.*\.vercel\.app$",
]

CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
CORS_ALLOW_HEADERS = list(default_headers) + ["authorization"]
CORS_ALLOW_CREDENTIALS = False

# --------------------------------------------------
# Database
# Auto-switch:
# - Local: SQLite
# - Render: PostgreSQL via DATABASE_URL
# --------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    import dj_database_url
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --------------------------------------------------
# Templates
# --------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pos.context_processors.user_role_context",
            ],
        },
    },
]

# --------------------------------------------------
# Internationalization
# --------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------
# Static files
# --------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --------------------------------------------------
# Media storage (Cloudinary)
# --------------------------------------------------
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# Most stable approach: use CLOUDINARY_URL
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "").strip()

# Fallback if CLOUDINARY_URL is not set
CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()

if not CLOUDINARY_URL and CLOUD_NAME and API_KEY and API_SECRET:
    CLOUDINARY_URL = f"cloudinary://{API_KEY}:{API_SECRET}@{CLOUD_NAME}"
    os.environ["CLOUDINARY_URL"] = CLOUDINARY_URL

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": CLOUD_NAME,
    "API_KEY": API_KEY,
    "API_SECRET": API_SECRET,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------
# Jazzmin configuration (FULL - unchanged)
# --------------------------------------------------
JAZZMIN_SETTINGS = {
    "site_title": "MyPOS Admin",
    "site_header": "MyPOS Admin Panel",
    "welcome_sign": "Selamat Datang di MyPOS",
    "site_brand": "MyPOS",
    "show_sidebar": True,
    "navigation_expanded": True,
    "custom_css": "admin/css/force_jazzmin_sidebar.css",
    "custom_js": "admin/js/force_sidebar_open.js",
    "icons": {
        "pos.Customer": "fas fa-user",
        "pos.Supplier": "fas fa-users-cog",
        "pos.Category": "fas fa-boxes",
        "pos.Unit": "fas fa-balance-scale",
        "pos.Product": "fas fa-box-open",
        "pos.Order": "fas fa-shopping-cart",
        "pos.Expense": "fas fa-coins",
        "pos.Shop": "fas fa-store",
        "pos.CustomUser": "fas fa-user-shield",
        "pos.Banner": "fas fa-image",
        "auth.Group": "fas fa-users",
        "pos.TokenProxy": "fas fa-key",
    },
    "custom_links": {
        "pos": [
            {"name": "Sales Report", "url": "/admin/reports/sales/", "icon": "fas fa-chart-line", "permissions": ["pos.view_order"]},
            {"name": "Expense Report", "url": "/admin/reports/expense/", "icon": "fas fa-file-invoice-dollar", "permissions": ["pos.view_expense"]},
            {"name": "Sales Chart", "url": "/admin/reports/sales-chart/", "icon": "fas fa-chart-pie", "permissions": ["pos.view_order"]},
            {"name": "Expense Chart", "url": "/admin/reports/expense-chart/", "icon": "fas fa-chart-area", "permissions": ["pos.view_expense"]},
        ]
    },
    "order_with_respect_to": [
        "pos.Customer", "pos.Supplier", "pos.Product", "pos.Order", "pos.OrderItem",
        "pos.Expense", "pos.Category", "pos.Unit", "pos.Shop", "pos.Banner",
        "auth.Group", "pos.CustomUser", "pos.TokenProxy",
    ],
    "hide_apps": ["auth", "authtoken"],
    "hide_models": ["auth.User", "auth.Group"],
    "show_ui_builder": False,
    "topmenu_links": [
        {"name": "Dashboard", "url": "/admin", "permissions": ["auth.view_user"]},
        {"model": "pos.CustomUser"},
    ],
    "side_menu": [
        {"app": "pos", "label": "Customers", "models": ["pos.Customer"]},
        {"app": "pos", "label": "Suppliers", "models": ["pos.Supplier"]},
        {"app": "pos", "label": "Products Category", "models": ["pos.Category"]},
        {"app": "pos", "label": "Products", "models": ["pos.Product"]},
        {"app": "pos", "label": "Orders", "models": ["pos.Order"]},
        {"app": "pos", "label": "Expense", "models": ["pos.Expense"]},
        {"app": "pos", "label": "Banners", "models": ["pos.Banner"]},
        {
            "label": "Reports",
            "icon": "fas fa-chart-line",
            "models": [
                {"name": "Sales Report", "url": "/admin/reports/sales/"},
                {"name": "Expense Report", "url": "/admin/reports/expense/"},
                {"name": "Sales Chart", "url": "/admin/reports/sales-chart/"},
                {"name": "Expense Chart", "url": "/admin/reports/expense-chart/"},
            ],
        },
        {
            "label": "Settings",
            "icon": "fas fa-cogs",
            "models": ["pos.Shop", "pos.Unit"],
        },
        {
            "label": "Admin Users",
            "icon": "fas fa-user-shield",
            "models": ["auth.Group", "pos.CustomUser", "pos.TokenProxy"],
        },
    ],
}
