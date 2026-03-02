"""
Django Settings for Chatbot Service with RAG
File: chatbot_service/chatbot_service/settings.py
"""

import os
import warnings
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# Suppress LangChain/HuggingFace OpenAI-related warnings (we use local embeddings)
warnings.filterwarnings("ignore", message=".*OPENAI_API_KEY.*")
warnings.filterwarnings("ignore", category=UserWarning, module="langchain")

# ==================== ENVIRONMENT SETUP ====================

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== CORE DJANGO SETTINGS ====================

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
JWT_ALGORITHM = 'HS256'

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

# ==================== APPLICATION DEFINITION ====================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'corsheaders',

    # Local
    'aichat_service',
]

# ==================== MIDDLEWARE ====================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'aichat_service.middleware.HeaderTenantMiddleware',  # Added for tenant isolation
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'chatbot_service.urls'
WSGI_APPLICATION = 'chatbot_service.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ==================== DATABASE ====================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
        'CONN_MAX_AGE': 600,
    }
}

# ==================== PASSWORD VALIDATION ====================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==================== INTERNATIONALISATION ====================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ==================== STATIC AND MEDIA FILES ====================

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==================== CORS ====================

CORS_ALLOW_CREDENTIALS = True

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    _cors_origins = os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173'
    )
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in _cors_origins.split(',')
        if origin.strip()
    ]

CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']

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

# ==================== REST FRAMEWORK ====================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'aichat_service.authentication.MicroserviceJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '500/hour',
        'user': '5000/hour',
    },
}

# ==================== SIMPLE JWT ====================

SIMPLE_JWT = {
    'SIGNING_KEY': JWT_SECRET_KEY,
    'ALGORITHM': JWT_ALGORITHM,
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': None,
}

# ==================== WEBHOOK / API KEY ====================
WEBHOOK_API_KEY = os.getenv('WEBHOOK_API_KEY', os.getenv('API_KEY', ''))
DOCUMENT_SERVICE_URL = os.getenv('DOCUMENT_SERVICE_URL', 'http://127.0.0.1:8003')
DOCUMENT_SERVICE_WEBHOOK_API_KEY = os.getenv('DOCUMENT_SERVICE_WEBHOOK_API_KEY', WEBHOOK_API_KEY)

# ==================== GROQ (FREE AI - replaces OpenAI for chat) ====================

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')

# ==================== AI PROVIDER SELECTION ====================

AI_PROVIDER = os.getenv('AI_PROVIDER', 'groq')
AI_MODEL = GROQ_MODEL if AI_PROVIDER == 'groq' else os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
AI_MAX_TOKENS = int(os.getenv('OPENAI_MAX_TOKENS', '500'))
AI_TEMPERATURE = float(os.getenv('OPENAI_TEMPERATURE', '0.7'))

# ==================== RAG SETTINGS ====================

DOCUMENT_CHUNK_SIZE = int(os.getenv('DOCUMENT_CHUNK_SIZE', '500'))
DOCUMENT_CHUNK_OVERLAP = int(os.getenv('DOCUMENT_CHUNK_OVERLAP', '50'))
MAX_DOCUMENT_SIZE_MB = int(os.getenv('MAX_DOCUMENT_SIZE_MB', '10'))

EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
EMBEDDING_DIMENSION = int(os.getenv('EMBEDDING_DIMENSION', '384'))

DEFAULT_LLM_MODEL = AI_MODEL
MAX_RESPONSE_TOKENS = AI_MAX_TOKENS
DEFAULT_TEMPERATURE = AI_TEMPERATURE

DEFAULT_RETRIEVAL_TOP_K = int(os.getenv('DEFAULT_RETRIEVAL_TOP_K', '5'))
DEFAULT_RELEVANCE_THRESHOLD = float(os.getenv('DEFAULT_RELEVANCE_THRESHOLD', '0.3'))

# ==================== CELERY ====================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = True   # Temporarily True to fix 'Processing' hang when worker is down
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

# ==================== VECTOR STORE ====================

CHROMADB_PERSIST_DIRECTORY = BASE_DIR / 'chromadb_data'
VECTOR_STORES_DIR = MEDIA_ROOT / 'vector_stores'

# ==================== CACHE ====================

if DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'chatbot-cache',
            'OPTIONS': {'MAX_ENTRIES': 1000},
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
            'KEY_PREFIX': 'chatbot',
            'TIMEOUT': 300,
        }
    }

# ==================== LOGGING ====================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} {process:d} {thread:d} - {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{levelname}] {asctime} - {message}',
            'style': '{',
        },
    },
    'filters': {
        'ignore_openai_warnings': {
            '()': 'django.utils.log.CallbackFilter',
            'callback': lambda record: 'OPENAI_API_KEY' not in record.getMessage(),
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'filters': ['ignore_openai_warnings'],
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'chatbot.log'),
            'maxBytes': 1024 * 1024 * 10,
            'backupCount': 5,
            'formatter': 'verbose',
            'filters': ['ignore_openai_warnings'],
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'aichat_service': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}

# ==================== REQUIRED DIRECTORIES ====================

for _dir in [
    BASE_DIR / 'logs',
    MEDIA_ROOT,
    VECTOR_STORES_DIR,
    CHROMADB_PERSIST_DIRECTORY,
]:
    Path(_dir).mkdir(parents=True, exist_ok=True)

# ==================== STARTUP INFO (dev only) ====================

if DEBUG:
    _db_engine = DATABASES['default']['ENGINE'].split('.')[-1]
    _groq_status = f"gsk_...{GROQ_API_KEY[-4:]}" if GROQ_API_KEY else "NOT CONFIGURED"
    print("=" * 70)
    print("Chatbot Service - Multi-Tenant Setup")
    print("=" * 70)
    print(f"  Database   : {DATABASES['default']['NAME']} ({_db_engine})")
    print(f"  AI Provider: {AI_PROVIDER.upper()}")
    print(f"  AI Model   : {AI_MODEL}")
    print(f"  Groq Key   : {_groq_status}")
    print(f"  Embeddings : {EMBEDDING_MODEL} (local, FREE)")
    print(f"  ChromaDB   : {CHROMADB_PERSIST_DIRECTORY}")
    print("=" * 70)