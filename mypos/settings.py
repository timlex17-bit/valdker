"""
Django settings for mypos project.
Cloudinary + Render READY (SQLite local safe)
"""

from pathlib import Path
from corsheaders.defaults import default_headers
import dj_database_url
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# =====================================================
# BASIC
# =====================================================
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-key")
DEBUG = os.environ.get("DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "valdker.onrender.com",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://valdker-vue-js.vercel.app",
    "https://valdker.onrender.com",
]

# =====================================================
# APPLICATIONS
# =====================================================
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

AUTH_USER_MODEL = "pos.CustomUser"

# =====================================================
# REST FRAMEWORK
# =====================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# =====================================================
# MIDDLEWARE
# =====================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

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

# =====================================================
# DATABASE (✅ FIX: SQLite local jangan pakai sslmode)
# =====================================================
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Render / production
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,  # aman untuk Postgres/MySQL
        )
    }
else:
    # Local Windows SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# =====================================================
# CORS
# =====================================================
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    "https://valdker-vue-js.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https:\/\/.*\.vercel\.app$",
]

CORS_ALLOW_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]

CORS_ALLOW_HEADERS = list(default_headers) + ["authorization"]

CORS_ALLOW_CREDENTIALS = False

# =====================================================
# TEMPLATES
# =====================================================
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

# =====================================================
# I18N
# =====================================================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# =====================================================
# STATIC FILES
# =====================================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# =====================================================
# CLOUDINARY (✅ ENV name harus benar)
# =====================================================
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.environ.get("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.environ.get("CLOUDINARY_API_KEY"),
    "API_SECRET": os.environ.get("CLOUDINARY_API_SECRET"),
}

# =====================================================
# DEFAULT PK
# =====================================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =====================================================
# JAZZMIN
# =====================================================
JAZZMIN_SETTINGS = {
    "site_title": "MyPOS Admin",
    "site_header": "MyPOS Admin Panel",
    "site_brand": "MyPOS",
    "welcome_sign": "Selamat Datang di MyPOS",
    "show_sidebar": True,
    "navigation_expanded": True,
    "custom_css": "admin/css/force_jazzmin_sidebar.css",
    "custom_js": "admin/js/force_sidebar_open.js",
}
