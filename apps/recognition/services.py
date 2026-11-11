"""
Recognition service.

Runs the configured RecognitionProvider against a scan's stored image and
normalises the provider output into an (unsaved) IdentifiedItem. Persisting
the item and transitioning the scan is done by apps.scans.services so both
writes happen in one transaction.
"""

import json
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.services import record_audit_event
from apps.catalog.models import Brand, Category
from apps.scans.models import IdentifiedItem

from .exceptions import (
    CorruptImageError,
    ProviderError,
    ProviderTimeoutError,
)
from .providers import RecognitionProvider, RecognitionResult, get_provider

logger = logging.getLogger(__name__)

FALLBACK_CATEGORY_SLUG = "uncategorized"
FALLBACK_CATEGORY_NAME = "Uncategorized"


def provider_log_label(provider: RecognitionProvider) -> str:
    return f"[MOCK] {provider.name}" if provider.is_mock else provider.name


def load_scan_image(scan):
    """Return (bytes, content_type) of the scan's first stored image."""
    image = scan.images.order_by("created_at").first()
    if image is None:
        raise CorruptImageError("scan has no image", user_message="No image was uploaded for this scan.")
    try:
        with default_storage.open(image.storage_key, "rb") as fh:
            data = fh.read()
    except FileNotFoundError as exc:
        raise CorruptImageError(
            "stored image missing", user_message="The uploaded image is no longer available."
        ) from exc
    return data, image.content_type


def recognize_scan(scan, timeout: int) -> tuple[RecognitionProvider, RecognitionResult]:
    """Run the configured provider on the scan's image."""
    provider = get_provider()
    image_bytes, content_type = load_scan_image(scan)
    logger.info("recognition.start scan=%s provider=%s", scan.public_id, provider_log_label(provider))
    try:
        result = provider.recognize(image_bytes, content_type, timeout=timeout)
    except TimeoutError as exc:
        raise ProviderTimeoutError("provider raised TimeoutError") from exc
    if not isinstance(result, RecognitionResult):
        raise ProviderError(f"provider returned {type(result).__name__}")
    return provider, result


def _clean_text(value, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _normalise_confidence(value) -> Decimal:
    try:
        confidence = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ProviderError(f"invalid confidence {value!r}") from exc
    if not confidence.is_finite() or not (Decimal("0") <= confidence <= Decimal("1")):
        raise ProviderError(f"confidence out of range {value!r}")
    return confidence


def _resolve_category(slug: str | None) -> Category:
    if slug:
        category = Category.objects.filter(slug=slugify(slug)).first()
        if category is not None:
            return category
    category, _ = Category.objects.get_or_create(
        slug=FALLBACK_CATEGORY_SLUG,
        defaults={"name": FALLBACK_CATEGORY_NAME, "description": "Items whose category was not identified."},
    )
    return category


def _resolve_brand(name: str | None) -> Brand | None:
    """Match an existing brand only; provider output never creates catalog rows."""
    if not name:
        return None
    return Brand.objects.filter(name__iexact=name.strip()).first() or Brand.objects.filter(
        slug=slugify(name)
    ).first()


def build_identified_item(scan, provider: RecognitionProvider, result: RecognitionResult) -> IdentifiedItem:
    """Validate provider output and return an unsaved IdentifiedItem."""
    title = _clean_text(result.title, 300)
    if not title:
        raise ProviderError("provider returned an empty title")
    if not isinstance(result.attributes, dict):
        raise ProviderError("provider attributes must be a dict")

    attributes = dict(result.attributes)
    for key, value in (("color", result.color), ("size", result.size)):
        if value:
            attributes[key] = _clean_text(value, 100)

    brand = _resolve_brand(result.brand_name)
    if result.brand_name and brand is None:
        attributes["provider_brand"] = _clean_text(result.brand_name, 200)

    condition = result.condition if result.condition in IdentifiedItem.Condition.values else None
    if result.condition and condition is None:
        attributes["provider_condition"] = _clean_text(result.condition, 50)

    if provider.is_mock:
        attributes["mock"] = True
    try:
        json.dumps(attributes)
    except (TypeError, ValueError) as exc:
        raise ProviderError("provider attributes are not JSON-serialisable") from exc

    return IdentifiedItem(
        scan=scan,
        category=_resolve_category(result.category_slug),
        brand=brand,
        title=title,
        model_name=_clean_text(result.model_name, 200),
        condition=condition or IdentifiedItem.Condition.UNKNOWN,
        attributes=attributes,
        confidence=_normalise_confidence(result.confidence),
        provider_name=provider.name,
        is_user_corrected=False,
    )


CORRECTABLE_FIELDS = ("title", "category", "brand", "model_name", "condition")


def correct_identified_item(item: IdentifiedItem, changes: dict, actor=None) -> IdentifiedItem:
    """
    Apply a user correction. The provider's original prediction is kept in
    attributes["provider_original"] the first time an item is corrected, so
    model-generated and manual values stay distinguishable.
    """
    with transaction.atomic():
        locked = IdentifiedItem.objects.select_for_update().get(pk=item.pk)
        if not locked.is_user_corrected:
            locked.attributes = {
                **locked.attributes,
                "provider_original": {
                    "title": locked.title,
                    "category": locked.category.slug,
                    "brand": locked.brand.name if locked.brand else None,
                    "model_name": locked.model_name,
                    "condition": locked.condition,
                    "confidence": str(locked.confidence),
                },
            }
        for field in CORRECTABLE_FIELDS:
            if field in changes:
                setattr(locked, field, changes[field])
        locked.is_user_corrected = True
        locked.save()
        record_audit_event(
            action="identified_item.corrected",
            target_type="Scan",
            target_id=str(locked.scan.public_id),
            actor=actor,
            metadata={"fields": sorted(f for f in CORRECTABLE_FIELDS if f in changes)},
        )
    return locked
