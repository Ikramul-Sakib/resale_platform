"""
Celery tasks for the scan workflow.

process_scan is idempotent: terminal scans are skipped, and retries only
happen for errors marked retryable, with bounded exponential backoff.
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.recognition import services as recognition_services
from apps.recognition.exceptions import (
    ProviderTimeoutError,
    RecognitionError,
    RecognitionNotConfiguredError,
)

from . import services as scan_services

logger = logging.getLogger(__name__)


def retry_countdown(retries: int) -> int:
    """Exponential backoff: base * 2**retries, capped."""
    return min(
        settings.RECOGNITION_RETRY_BACKOFF_SECONDS * (2**retries),
        settings.RECOGNITION_RETRY_BACKOFF_MAX_SECONDS,
    )


@shared_task(bind=True, acks_late=True)
def process_scan(self, scan_id: int) -> str | None:
    scan = scan_services.start_processing(scan_id)
    if scan is None:
        logger.info("scan.skip scan_id=%s reason=missing_or_terminal", scan_id)
        return None

    attempt = self.request.retries
    max_retries = settings.RECOGNITION_MAX_RETRIES
    while True:
        try:
            try:
                provider, result = recognition_services.recognize_scan(
                    scan, timeout=settings.RECOGNITION_PROVIDER_TIMEOUT_SECONDS
                )
            except SoftTimeLimitExceeded as exc:
                raise ProviderTimeoutError("task soft time limit exceeded") from exc
            item = recognition_services.build_identified_item(scan, provider, result)
            break
        except RecognitionError as exc:
            if exc.retryable and attempt < max_retries:
                countdown = retry_countdown(attempt)
                logger.warning(
                    "scan.retry scan=%s error=%s attempt=%s/%s countdown=%ss eager=%s",
                    scan.public_id, type(exc).__name__, attempt + 1, max_retries, countdown,
                    bool(self.request.is_eager),
                )
                if self.request.is_eager:
                    # No broker (dev eager mode): retry inline without sleeping.
                    attempt += 1
                    continue
                raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)
            logger.warning(
                "scan.failed scan=%s error=%s retryable=%s attempts=%s",
                scan.public_id, type(exc).__name__, exc.retryable, attempt + 1,
            )
            return scan_services.fail_scan(scan, exc.user_message).status
        except ImproperlyConfigured:
            logger.error("scan.failed scan=%s error=ImproperlyConfigured", scan.public_id)
            return scan_services.fail_scan(scan, RecognitionNotConfiguredError.user_message).status
        except Exception:
            logger.exception("scan.failed scan=%s error=unexpected", scan.public_id)
            return scan_services.fail_scan(scan, scan_services.GENERIC_FAILURE_MESSAGE).status

    completed = scan_services.complete_scan(scan, item)
    logger.info(
        "scan.completed scan=%s provider=%s confidence=%s",
        completed.public_id, recognition_services.provider_log_label(provider), item.confidence,
    )
    return completed.status
