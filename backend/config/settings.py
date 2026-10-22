"""Réglages Django d'Assista-Crise. Variables d'environnement : DOCUMENTATION.md, § 5.4."""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_secret(name, default=None):
    """Valeur du fichier NAME_FILE (secret Docker) si défini, sinon de la variable NAME."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path) as f:
            return f.read().strip()
    return os.environ.get(name) or default   # variable vide = absente


# Clé de repli publique (historique git) : acceptée seulement avec DEBUG=True ou en tests.
_DEV_FALLBACK_SECRET_KEY = 'django-insecure-HSLgGBNlaGBJ4kyaracScLRPa3tFJhK6LOEbYQs9ipBu-DaMMQfey725-fB-uq8Dabk'
SECRET_KEY = env_secret('SECRET_KEY', _DEV_FALLBACK_SECRET_KEY)

# Clés de chiffrement des données personnelles, sans valeur de repli (DOCUMENTATION.md, § 10.1).
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')
FIELD_BLIND_INDEX_KEY = os.environ.get('FIELD_BLIND_INDEX_KEY', '')

FILE_ENCRYPTION_KEY = os.environ.get('FILE_ENCRYPTION_KEY', '')

# email est chiffré : l'unicité exigée par auth.E003 porte sur User.email_bidx
SILENCED_SYSTEM_CHECKS = ['auth.E003']

# Toute erreur journalisée part par email (ADMINS) et sur un salon Matrix : DOCUMENTATION.md, § 5.7.
ADMINS = [("Sylvain", "sylvain.hazera@gmail.com")]
MANAGERS = ADMINS
SERVER_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@assista-crise.fr')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        },
        'matrix_alert': {
            'level': 'ERROR',
            'class': 'core.logging_handlers.MatrixAlertHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'mail_admins', 'matrix_alert'],
        'level': 'INFO',
    },
}

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

_RUNNING_TESTS = 'pytest' in sys.modules or sys.argv[1:2] == ['test']
if SECRET_KEY == _DEV_FALLBACK_SECRET_KEY and not (DEBUG or _RUNNING_TESTS):
    raise ImproperlyConfigured(
        "SECRET_KEY (ou SECRET_KEY_FILE) n'est pas défini : refus de démarrer avec la clé de repli, "
        "publique. En dev : ./scripts/init-secrets.sh (ajoute SECRET_KEY au .env) ou DEBUG=True."
    )


ALLOWED_HOSTS = [
    'localhost', '172.16.1.114', '127.0.0.1',
    'assista-crise.fr', 'www.assista-crise.fr', 'demo.assista-crise.fr', 'assista-crise.duckdns.org',
    # marque blanche : le domaine du partenaire est un CNAME de cj., les deux Host arrivent ici
    'cj.assista-crise.fr', 'app.reserve-resilience.org',
    # appels internes des services-ponts via http://backend:8000/
    'backend',
]

CSRF_TRUSTED_ORIGINS = [
    "https://assista-crise.fr",
    "https://www.assista-crise.fr",
    "https://demo.assista-crise.fr",
    "https://demo.assista-crise.fr:4200",
    "https://assista-crise.duckdns.org",
    "https://cj.assista-crise.fr",
    "https://app.reserve-resilience.org",

    "http://172.16.1.114",
    "https://172.16.1.114",
    "http://172.16.1.114:4200",
    "http://172.16.1.114:8085",  # SSO Matrix (login/authorize en clair, voir proxy/nginx.conf)

    "http://localhost",
    "http://localhost:4200",
]

AUTH_USER_MODEL = 'core.User'

INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'django_filters',
    'core',
    "django.contrib.gis",
    'oauth2_provider',
    'django_prometheus',
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',   # doit rester en premier
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.NoCacheApiMiddleware',
    'core.middleware.AuditTraceMiddleware',
    'core.middleware.GeoResolutionBudgetMiddleware',
    'django_prometheus.middleware.PrometheusAfterMiddleware',    # doit rester en dernier
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASES = {
    'default': {
        # PostGIS instrumenté : requêtes, erreurs et latence SQL sur /metrics
        'ENGINE': 'django_prometheus.db.backends.postgis',
        'NAME': os.environ.get('DB_NAME', 'assista-db'),
        # pas de repli (l'ancien 'admin'/'admin' était celui de la prod) : KeyError si absent
        'USER': os.environ['DB_USER'],
        'PASSWORD': env_secret('DB_PASS') or os.environ['DB_PASS'],   # KeyError si absent : échec explicite
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': '5432',
        # le rôle de prod (assista_app) n'est pas superuser : la base de test clone un modèle
        # où PostGIS est déjà installé, faute de pouvoir lancer CREATE EXTENSION
        'TEST': {
            'NAME': 'test_assista-db',
            'TEMPLATE': 'template_postgis',
        },
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CORS_ALLOWED_ORIGINS = [
    "http://172.16.1.114:4200",
    "http://assista-crise.duckdns.org",
    "http://demo.assista-crise.fr",
    "http://localhost",              # dev via le proxy Nginx (le front appelle localhost:8000)
    "http://127.0.0.1",
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://frontend:4200",  # Pour Docker
    "https://172.16.1.114:4200",
    "https://assista-crise.duckdns.org",
    "https://assista-crise.fr",
    "https://demo.assista-crise.fr",
    "https://demo.assista-crise.fr:4200",
    "https://cj.assista-crise.fr",
    "https://app.reserve-resilience.org",
    "https://localhost:4200",
    "https://127.0.0.1:4200",
    "https://frontend:4200",  # Pour Docker
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-environment',  # zone PROD/DEMO, ajoutée à chaque requête par l'intercepteur Angular
]

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
}

from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

AUTH_USER_MODEL = 'core.User'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

EMAIL_HOST = os.environ.get('EMAIL_HOST', 'mailhog')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 1025))

EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False') == 'True'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False') == 'True'

EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env_secret('EMAIL_HOST_PASSWORD', '')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@assista-crise.fr')

SERVER_URL = os.environ.get(
    "SERVER_URL",
    "https://www.assista-crise.fr"
)

# Fournisseur OIDC : connexion à Matrix avec le compte Assista-Crise (DOCUMENTATION.md, § 7.1)
OAUTH2_PROVIDER = {
    "OIDC_ENABLED": True,
    # PEM sur une ligne (\n littéraux) : un --env-file Docker n'accepte pas de valeur multiligne
    "OIDC_RSA_PRIVATE_KEY": os.environ.get("OIDC_RSA_PRIVATE_KEY", "").replace("\\n", "\n"),
    "OAUTH2_VALIDATOR_CLASS": "core.oidc.AssistaCriseOIDCValidator",
    # fixe : Synapse appelle /o/token/ via backend:8000, l'iss déduit du Host serait faux
    "OIDC_ISS_ENDPOINT": os.environ.get("OIDC_ISS_ENDPOINT", "https://www.assista-crise.fr/o"),
    "SCOPES": {
        "openid": "Identification (OpenID Connect)",
        "profile": "Nom affiché",
        "email": "Adresse email",
    },
    "PKCE_REQUIRED": False,
    # le jeton ne sert qu'à l'échange de code par Synapse
    "ACCESS_TOKEN_EXPIRE_SECONDS": 600,
}

# Clé privée des jetons de connexion à Grafana (core/grafana.py), PEM sur une ligne comme
# OIDC_RSA_PRIVATE_KEY. Vide : la supervision dans l'admin répond 503, le reste fonctionne.
GRAFANA_JWT_PRIVATE_KEY = os.environ.get("GRAFANA_JWT_PRIVATE_KEY", "").replace("\\n", "\n")

# identique dans matrix-bridge et dans la config Synapse (voir core/matrix.py)
MATRIX_SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", "matrix.assista-crise.local")

# jours de conservation de l'AuditLog (purge : manage.py purge_audit_logs)
AUDIT_LOG_RETENTION_DAYS = int(os.environ.get('AUDIT_LOG_RETENTION_DAYS', 30))

# Détection automatique de messages d'urgence (mots-clés, canal EMCOM) sur le réseau Meshtastic :
# coupée le 22/10/2026 à la demande de l'exploitant -- trop de faux positifs sur les canaux
# communautaires (télémétrie « !SOS » d'autres réseaux, tout le trafic de Fr_EMCOM, et nos
# propres alertes séisme réentendues). True pour la réactiver ; MeshCore n'est pas concerné.
DETECTION_SOS_MESHTASTIC = os.environ.get('DETECTION_SOS_MESHTASTIC', 'False') == 'True'


# Satellites : DOCUMENTATION.md, § 7.3
SATELLITE_SEUIL_INACTIF_MINUTES = int(os.environ.get('SATELLITE_SEUIL_INACTIF_MINUTES', 15))
SATELLITE_SEUIL_PERDU_MINUTES = int(os.environ.get('SATELLITE_SEUIL_PERDU_MINUTES', 120))

SATELLITE_SUPERVISION_RAYON_LIMITROPHE_KM = int(os.environ.get('SATELLITE_SUPERVISION_RAYON_LIMITROPHE_KM', 15))

# True uniquement sur un satellite « full » : le central ne doit jamais se synchroniser vers lui-même
INSTANCE_SATELLITE_LOCALE = os.environ.get('INSTANCE_SATELLITE_LOCALE', 'False') == 'True'

# Satellite : l'application est ouverte depuis un téléphone ou un PC du réseau local, par l'IP
# du satellite (inconnue d'avance). Tout nom d'hôte est accepté ; le filtrage aux seules
# adresses privées (RFC 1918) est fait par le nginx du satellite (satellite/nginx-satellite.conf).
if os.environ.get('SATELLITE_WEB_LOCAL', 'False') == 'True':
    ALLOWED_HOSTS = ['*']

SATELLITE_SYNC_SORTANT_INTERVALLE_S = int(os.environ.get('SATELLITE_SYNC_SORTANT_INTERVALLE_S', 300))

# compte de service de ce satellite auprès du central (SATELLITE_ID : obtenu à l'enrôlement)
SATELLITE_CENTRAL_URL = os.environ.get('SATELLITE_CENTRAL_URL', '')
SATELLITE_ID = os.environ.get('SATELLITE_ID', '')
SATELLITE_EMAIL = os.environ.get('SATELLITE_EMAIL', '')
SATELLITE_PASSWORD = os.environ.get('SATELLITE_PASSWORD', '')

# identité du sous-traitant RGPD citée dans l'email de convention (core/convention_sous_traitance.py)
CONVENTION_SOUS_TRAITANT_NOM = os.environ.get('CONVENTION_SOUS_TRAITANT_NOM', 'Sylvain HAZERA')
CONVENTION_SOUS_TRAITANT_ADRESSE = os.environ.get(
    'CONVENTION_SOUS_TRAITANT_ADRESSE', '5 place Gabriel Fauré, 33200 Bordeaux',
)
CONVENTION_SOUS_TRAITANT_EMAIL = os.environ.get('CONVENTION_SOUS_TRAITANT_EMAIL', 'contact@assista-crise.fr')

USE_X_FORWARDED_HOST = True

SECURE_PROXY_SSL_HEADER = (
    ('HTTP_X_FORWARDED_PROTO', 'https')
)

# Activés seulement hors DEBUG pour ne pas casser le dev local en HTTP.
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # False seulement pour un SSO Matrix servi en HTTP (port 8085, ancienne .113) : jamais en prod
    cookies_secure = os.environ.get('COOKIES_SECURE_OVERRIDE', 'True') == 'True'
    SESSION_COOKIE_SECURE = cookies_secure
    CSRF_COOKIE_SECURE = cookies_secure


# Celery : simulation d'inondation, trop longue pour une requête HTTP (DOCUMENTATION.md, § 5.8)
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_TASK_ACKS_LATE = True  # une tâche interrompue (redéploiement) est relancée

