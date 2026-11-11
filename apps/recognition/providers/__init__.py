"""
Recognition provider registry.

The active provider is selected by the RECOGNITION_PROVIDER setting
(environment variable). Values are either a registered short name or a
dotted path to a RecognitionProvider subclass. An empty value means no
provider is configured and recognition is refused.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from ..exceptions import RecognitionNotConfiguredError
from .base import RecognitionProvider, RecognitionResult

PROVIDER_REGISTRY = {
    "mock": "apps.recognition.providers.mock.MockRecognitionProvider",
}

__all__ = ["PROVIDER_REGISTRY", "RecognitionProvider", "RecognitionResult", "get_provider"]


def get_provider() -> RecognitionProvider:
    key = (settings.RECOGNITION_PROVIDER or "").strip()
    if not key:
        raise RecognitionNotConfiguredError("RECOGNITION_PROVIDER is empty")

    path = PROVIDER_REGISTRY.get(key.lower(), key)
    if "." not in path:
        raise ImproperlyConfigured(f"Unknown RECOGNITION_PROVIDER {key!r}.")
    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(f"Cannot import RECOGNITION_PROVIDER {key!r}.") from exc
    if not (isinstance(provider_class, type) and issubclass(provider_class, RecognitionProvider)):
        raise ImproperlyConfigured(f"RECOGNITION_PROVIDER {key!r} is not a RecognitionProvider.")
    return provider_class()
