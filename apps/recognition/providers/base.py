"""
Abstract recognition provider interface.

Concrete providers receive sanitised image bytes and return a
RecognitionResult. They must raise ProviderTimeoutError /
ProviderUnavailableError for transient failures (retried by the task) and
ProviderError for permanent failures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class RecognitionResult:
    """
    Provider output. Optional fields are None when the provider does not
    support them; they must never be filled with guessed values.
    """

    title: str
    confidence: Decimal
    category_slug: str | None = None
    brand_name: str | None = None
    model_name: str | None = None
    color: str | None = None
    size: str | None = None
    condition: str | None = None
    attributes: dict = field(default_factory=dict)


class RecognitionProvider(ABC):
    """Base class for all recognition providers."""

    #: Stored in IdentifiedItem.provider_name and written to logs.
    name: str = ""
    #: True for providers that do not perform real recognition.
    is_mock: bool = False

    @abstractmethod
    def recognize(self, image_bytes: bytes, content_type: str, *, timeout: int) -> RecognitionResult:
        """Identify the item in ``image_bytes`` within ``timeout`` seconds."""
