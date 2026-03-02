"""
Django settings for tenantiq project.
Schema-based multi-tenancy via django-tenants.
"""
from datetime import timedelta
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ==========================
# SECURITY
# ==========================
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

DEBUG = os.getenv("DEBUG", "True") == "True"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


# ==========================
# APPLICATIONS
# ==========================
# django-tenants requires apps to be split into SHARED_APPS and TENANT_APPS.
#
# SHARED_APPS  → live in the 'public' schema, shared across all tenants
#                (e.g. Tenant, Domain, global subscription data)
#
# TENANT_APPS  → copied into every tenant's own schema
#                (e.g. users, core business logic, admin)
#
# INSTALLED_APPS is then built by merging both lists (django-tenants convention).

SHARED_APPS = [
    "django_tenants",                 # must be first
    "django.contrib.contenttypes",    # must be in shared
    "django.contrib.auth",            # moved here
    "django.contrib.sessions",        # moved here
    "django.contrib.admin",           # moved here
    "django.contrib.messages",        # moved here
    'corsheaders',
    # Your shared apps:
    "accounts",
    "subscriptions",
]

TENANT_APPS = [
    "django.contrib.staticfiles",     # staticfiles can stay in tenant

    # Your per-tenant apps:
    "core",
    "tenants",
    "user_management",

    # Third-party (needs to be in tenant scope):
    "rest_framework",
    
    "django_extensions",
]


# Build INSTALLED_APPS — shared first, then tenant-only apps
INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

# Which models django-tenants uses for routing
TENANT_MODEL = "accounts.Tenant"
TENANT_DOMAIN_MODEL = "accounts.Domain"

# Custom user model
AUTH_USER_MODEL = "accounts.User"


# ==========================
# MIDDLEWARE
# ==========================
# TenantMainMiddleware MUST be first — it resolves the tenant from the domain
# before any other middleware or view runs.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",        # ← Move to FIRST
    "django_tenants.middleware.main.TenantMainMiddleware",  # ← Second
    "accounts.middleware.CorsMiddleware",           # ← Remove this (likely redundant/conflicting)
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ==========================
# DATABASE
# ==========================
# django-tenants requires its own PostgreSQL backend and router.
# Everything else stays the same.
DATABASES = {
    "default": {
          'ENGINE': os.getenv('DB_ENGINE'),  # ← replaces django.db.backends.postgresql
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT"),
    }
}

DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]


# ==========================
# TEMPLATES
# ==========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tenantiq.wsgi.application"
ROOT_URLCONF = "tenantiq.urls"


# ==========================
# PASSWORD VALIDATION
# ==========================
# Removed the duplicate MinimumLengthValidator that was there before.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ==========================
# REST FRAMEWORK
# ==========================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}


# ==========================
# JWT (SimpleJWT)
# ==========================
SIMPLE_JWT = {
    "SIGNING_KEY": JWT_SECRET_KEY,
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
}


# ==========================
# CORS
# ==========================
# Note: CORS_ALLOW_ALL_ORIGINS=True overrides CORS_ALLOWED_ORIGINS entirely.
# Keep True for local dev, set to False in production and use CORS_ALLOWED_ORIGINS.
CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
).split(",")

CORS_ALLOW_ALL_ORIGINS = True   # True in dev, False in production automatically
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]



CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-api-key",
    "x-tenant-id",       
    "X-Tenant-ID",       
]


# ==========================
# EMAIL
# ==========================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "tenantiq07@gmail.com")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# ==========================
# RAZORPAY
# ==========================
RAZORPAY_CURRENCY = "INR"
RAZORPAY_PAYMENT_CAPTURE = 1
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")


# ==========================
# INTERNATIONALIZATION
# ==========================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ==========================
# STATIC FILES
# ==========================
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# ==========================
# DEFAULT PRIMARY KEY
# ==========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"