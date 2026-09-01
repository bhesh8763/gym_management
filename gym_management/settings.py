"""
Django settings for gym_management project.
"""
from pathlib import Path
from decouple import config
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── SECURITY ────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1').split(',')

# ─── APPLICATIONS ────────────────────────────────────────────────────────────
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.members',
    'apps.memberships',
    'apps.attendance',
    'apps.payments',
    'apps.staff',
    'apps.trainers',
    'apps.workouts',
    'apps.diet',
    'apps.progress',
    'apps.lockers',
    'apps.equipment',
    'apps.notifications',
    'apps.reports',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── MIDDLEWARE ───────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gym_management.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        # Use explicit loaders so the cached.Loader is NOT used in development.
        # APP_DIRS: True forces the cached loader even in DEBUG — we avoid that here.
        'APP_DIRS': False,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
        },
    },
]

WSGI_APPLICATION = 'gym_management.wsgi.application'

# ─── DATABASE ─────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='gym_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# ─── CUSTOM USER MODEL ────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'

# ─── PASSWORD VALIDATION ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── INTERNATIONALISATION ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kathmandu'
USE_I18N = True
USE_TZ = True

# ─── STATIC & MEDIA ───────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── AUTH (for template views) ────────────────────────────────────────────────
LOGIN_URL = '/api/auth/login/'
LOGIN_REDIRECT_URL = '/members/ui/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── DJANGO REST FRAMEWORK ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # ── Throttling ────────────────────────────────────────────────────────
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '50/hour',
        'user': '200/hour',
        'auth': '10/hour',
        'membership-write': '30/min',
    },
}

# ─── SIMPLE JWT ───────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_OBTAIN_SERIALIZER': 'apps.accounts.serializers.CustomTokenObtainPairSerializer',
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    # Frontend served by Live Server or serve_https.py
    'http://localhost:5500',
    'http://127.0.0.1:5500',
    'http://192.168.100.234:5500',
    'https://localhost:5500',
    'https://127.0.0.1:5500',
    'https://192.168.100.234:5500',
]
CORS_ALLOW_CREDENTIALS = True

# ─── EMAIL ─────────────────────────────────────────────────────────────────────
# In development: print emails to the console.
# In production: switch to smtp and set EMAIL_HOST, EMAIL_PORT, etc. via .env
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Gym Management <noreply@gym.local>')

# Frontend base URL — used in password reset emails
FRONTEND_URL = config('FRONTEND_URL', default='http://192.168.100.234:5500')
# ─── KHALTI (sandbox) ───────────────────────────────────────────────────────
# Get KHALTI_SECRET_KEY from your merchant dashboard at test-admin.khalti.com
# (Sign up as a merchant there — login OTP for sandbox is always 987654).
# dev.khalti.com is the sandbox base URL; switch to https://khalti.com/api/v2/
# only once you have a live merchant account with production keys.
KHALTI_SECRET_KEY = config('KHALTI_SECRET_KEY', default='')
KHALTI_BASE_URL = config('KHALTI_BASE_URL', default='https://dev.khalti.com/api/v2')
KHALTI_WEBHOOK_URL = config('KHALTI_WEBHOOK_URL', default='')


# ─── ESEWA (sandbox) ────────────────────────────────────────────────────────
# eSewa ePay v2. Test merchant code EPAYTEST / test secret key 8gBm/:&EnhH.1/q
# are eSewa's own published sandbox credentials — safe to default to them for
# development. Override with real values in .env for production.
# Docs: https://developer.esewa.com.np/pages/Epay
ESEWA_MERCHANT_CODE = config('ESEWA_MERCHANT_CODE', default='EPAYTEST')
ESEWA_SECRET_KEY = config('ESEWA_SECRET_KEY', default='8gBm/:&EnhH.1/q')
ESEWA_BASE_URL = config(
    'ESEWA_BASE_URL', default='https://rc-epay.esewa.com.np/api/epay/main/v2/form'
)
ESEWA_STATUS_CHECK_URL = config(
    'ESEWA_STATUS_CHECK_URL', default='https://rc.esewa.com.np/api/epay/transaction/status/'
)