"""
ValuLens Django settings — development overrides.

Loaded when DJANGO_SETTINGS_MODULE=config.settings.dev
"""

from .base import *  # noqa: F401, F403

# SECURITY
# -----------------------------------------------------------------------------
DEBUG = True

# Allow all hosts in dev
ALLOWED_HOSTS = ["*"]


# EMAIL — console backend for development
# -----------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# CELERY — run tasks eagerly (synchronously) if Redis is unavailable
# -----------------------------------------------------------------------------
if not CELERY_BROKER_URL:  # noqa: F405
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True


# DRF — enable browsable API in dev
# -----------------------------------------------------------------------------
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Relax throttling in dev
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": "1000/minute",
    "user": "5000/minute",
}


# LOGGING — more verbose in dev
# -----------------------------------------------------------------------------
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # noqa: F405
LOGGING["loggers"]["django.db.backends"] = {  # noqa: F405
    "handlers": ["console"],
    "level": "WARNING",  # Set to DEBUG to see all SQL queries
    "propagate": False,
}
