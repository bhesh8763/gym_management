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
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost').split(',')
# Render publishes the service's real public hostname in RENDER_EXTERNAL_HOSTNAME
# (a random suffix is appended when the requested name is taken, e.g.
# fitcore-k5zr.onrender.com).  Append it unconditionally so host checks never
# reject requests with a 400 DisallowedHost, whatever the env var says.
_render_host = config('RENDER_EXTERNAL_HOSTNAME', default='')
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

# ─── PRODUCTION SECURITY (env-gated, off by default) ────────────────────────────
# These default OFF so local dev is unaffected. Setting the matching env vars to
# True / nonzero in .env when we deploy is the entire path to a hardened production
# config — no code change required.
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config('SECURE_CONTENT_TYPE_NOSNIFF', default=True, cast=bool)
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True

# Behind Render's (or any) TLS-terminating proxy, trust X-Forwarded-Proto so
# request.is_secure() and absolute URLs (password-reset emails) use https.
# Off by default like the rest of this block — enable via .env on deploy.
SECURE_PROXY_SSL_HEADER = (
    ('HTTP_X_FORWARDED_PROTO', 'https')
    if config('TRUST_X_FORWARDED_PROTO', default=False, cast=bool)
    else None
)

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
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.facebook',
    'dj_rest_auth',
    'dj_rest_auth.registration',
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
    'apps.dataimport',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── MIDDLEWARE ───────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
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

# Cap request body size to prevent oversized uploads (covers Staff/Member profile photo uploads)
DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=5242880, cast=int)  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=5242880, cast=int)  # 5MB

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
STATICFILES_DIRS = [BASE_DIR / 'static']

# Serve the static frontend (frontend/) at the site root in production:
# WHITENOISE_INDEX_FILE maps "/" to frontend/index.html, so one service hosts
# the whole UI + API at a single origin (same-origin /api, no CORS needed).
WHITENOISE_ROOT = BASE_DIR / 'frontend'
WHITENOISE_INDEX_FILE = True

# Compressed (non-manifest) static storage — ships .gz/.br on collectstatic
# without ManifestStaticFilesStorage's hard failure on any stale reference.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── AUTH (for template views) ────────────────────────────────────────────────
LOGIN_URL = '/api/auth/login/'
LOGIN_REDIRECT_URL = '/members/ui/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── DJANGO REST FRAMEWORK ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.accounts.authentication.VersionedJWTAuthentication',
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
        'anon': '200/hour',
        'user': '2000/hour',
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
    'http://localhost:8000',
    'http://127.0.0.1:8000',
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

# Extra origins from env (comma-separated), e.g. a split frontend deploy:
#   CORS_ALLOWED_ORIGINS=https://fitcore.example.com,https://www.fitcore.example.com
CORS_ALLOWED_ORIGINS += [
    origin.strip()
    for origin in config('CORS_ALLOWED_ORIGINS', default='').split(',')
    if origin.strip()
]

# ─── CSRF ─────────────────────────────────────────────────────────────────────
# Trusted origins for CSRF in production.  Django requires the full scheme,
# so these must start with https:// (or http:// for local dev).
# Override via CSRF_TRUSTED_ORIGINS env var as a comma-separated list:
#   CSRF_TRUSTED_ORIGINS=https://fitcore.example.com,https://www.fitcore.example.com
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:5500,http://127.0.0.1:5500',
).split(',')
# Same auto-discovered Render host (see SECURITY section) for CSRF origin checks.
if _render_host:
    _render_origin = f'https://{_render_host}'
    if _render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_render_origin)

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

# ─── LOGGING ─────────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file_general': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'general.log',
            'maxBytes': 5 * 1024 * 1024,  # 5 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_errors': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'errors.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_security': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'security.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_reminders': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'reminders.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_general'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['file_errors', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file_security'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['file_general'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file_general', 'file_errors'],
            'level': 'INFO',
            'propagate': True,
        },
        'apps.notifications.management.commands.send_reminders': {
            'handlers': ['file_reminders', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.notifications.management.commands.send_scheduled_notifications': {
            'handlers': ['file_reminders', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

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

# ─── ALLAUTH ────────────────────────────────────────────────────────────────
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = 1

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_EMAIL_VERIFICATION = 'none'

LOGIN_REDIRECT_URL = config('FRONTEND_URL', default='http://localhost:5500')
LOGOUT_REDIRECT_URL = config('FRONTEND_URL', default='http://localhost:5500')

# Social account providers
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID', default=''),
            'secret': config('GOOGLE_CLIENT_SECRET', default=''),
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
    },
    'facebook': {
        'APP': {
            'client_id': config('FACEBOOK_APP_ID', default=''),
            'secret': config('FACEBOOK_APP_SECRET', default=''),
            'key': '',
        },
        'SCOPE': ['email', 'public_profile'],
        'AUTH_PARAMS': {'auth_type': 'reauthenticate'},
    },
}

# dj-rest-auth configuration
REST_USE_JWT = True
JWT_AUTH_HTTPONLY = False

REST_AUTH = {
    'TOKEN_MODEL': None,
    'USE_JWT': True,
    'JWT_AUTH_HTTPONLY': False,
    # dj-rest-auth (social login) must embed the same claims — most
    # importantly token_version — into the JWTs it issues for
    # Google/Facebook sessions.
    'JWT_TOKEN_CLAIMS_SERIALIZER': 'apps.accounts.social_claims.SocialTokenObtainPairSerializer',
}

SOCIALACCOUNT_LOGIN_REDIRECT_URL = config('FRONTEND_URL', default='http://localhost:5500')
SOCIALACCOUNT_SIGNUP_REDIRECT_URL = config('FRONTEND_URL', default='http://localhost:5500')