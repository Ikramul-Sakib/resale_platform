"""
Scan lifecycle service.

Status transitions: pending -> processing -> completed | failed.
Terminal states are final; repeated task deliveries are no-ops.
"""

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import record_audit_event
from apps.recognition.images import validate_and_sanitize

from .models import Scan, ScanImage

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    Scan.Status.PENDING: {Scan.Status.PROCESSING, Scan.Status.FAILED},
    Scan.Status.PROCESSING: {Scan.Status.PROCESSING, Scan.Status.COMPLETED, Scan.Status.FAILED},
    Scan.Status.COMPLETED: set(),
    Scan.Status.FAILED: set(),
}

GENERIC_FAILURE_MESSAGE = "Something went wrong while processing this scan. Please try again."


class InvalidScanTransition(Exception):
    pass


class GuestScanLimitExceeded(Exception):
    user_message = "You've reached the guest scan limit. Please sign in or try again later."


def _check_transition(scan: Scan, new_status: str) -> None:
    if new_status not in ALLOWED_TRANSITIONS[Scan.Status(scan.status)]:
        raise InvalidScanTransition(f"{scan.status} -> {new_status}")


def guest_scans_remaining(session_key: str) -> int:
    window_start = timezone.now() - timedelta(minutes=settings.GUEST_SCAN_RATE_LIMIT_WINDOW_MINUTES)
    used = Scan.objects.filter(
        user__isnull=True, session_key=session_key, created_at__gte=window_start
    ).count()
    return max(settings.GUEST_SCAN_RATE_LIMIT - used, 0)


def create_scan(uploaded_file, *, user=None, session_key: str = "") -> Scan:
    """
    Validate and sanitise an upload, store it privately, create the Scan and
    ScanImage atomically, and enqueue recognition after commit.

    Authenticated users own the scan via ``user``; guests via ``session_key``.
    Raises ImageValidationError subclasses or GuestScanLimitExceeded.
    """
    is_guest = user is None or not user.is_authenticated
    if is_guest:
        if not session_key:
            raise ValueError("Guest scans require a session key.")
        if guest_scans_remaining(session_key) <= 0:
            raise GuestScanLimitExceeded()

    image = validate_and_sanitize(uploaded_file)

    public_id = uuid.uuid4()
    storage_key = default_storage.save(
        f"scans/{public_id}/{uuid.uuid4().hex}.{image.extension}", ContentFile(image.content)
    )
    try:
        with transaction.atomic():
            scan = Scan.objects.create(
                public_id=public_id,
                user=None if is_guest else user,
                session_key=session_key if is_guest else "",
            )
            ScanImage.objects.create(
                scan=scan,
                storage_key=storage_key,
                content_type=image.content_type,
                file_size=image.size,
                sha256=image.sha256,
            )
            record_audit_event(
                action="scan.created",
                target_type="Scan",
                target_id=str(scan.public_id),
                actor=None if is_guest else user,
                metadata={"guest": is_guest, "content_type": image.content_type, "file_size": image.size},
            )
            transaction.on_commit(lambda: enqueue_scan(scan.pk), robust=True)
    except Exception:
        default_storage.delete(storage_key)
        raise

    logger.info("scan.created scan=%s guest=%s", scan.public_id, is_guest)
    return scan


def enqueue_scan(scan_id: int) -> None:
    from .tasks import process_scan

    process_scan.delay(scan_id)


def start_processing(scan_id: int) -> Scan | None:
    """
    Lock the scan and move it to processing. Returns None if the scan no
    longer exists or is already terminal (idempotent redelivery).
    """
    with transaction.atomic():
        scan = Scan.objects.select_for_update().filter(pk=scan_id).first()
        if scan is None or scan.status in (Scan.Status.COMPLETED, Scan.Status.FAILED):
            return None
        _check_transition(scan, Scan.Status.PROCESSING)
        scan.status = Scan.Status.PROCESSING
        scan.save(update_fields=["status"])
    return scan


def complete_scan(scan: Scan, identified_item) -> Scan:
    """Persist the identification and mark the scan completed in one transaction."""
    with transaction.atomic():
        locked = Scan.objects.select_for_update().get(pk=scan.pk)
        _check_transition(locked, Scan.Status.COMPLETED)
        identified_item.scan = locked
        identified_item.save()
        locked.status = Scan.Status.COMPLETED
        locked.error_message = ""
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "error_message", "completed_at"])
    return locked


def fail_scan(scan: Scan, user_message: str) -> Scan:
    """Mark the scan failed with a user-safe message."""
    with transaction.atomic():
        locked = Scan.objects.select_for_update().get(pk=scan.pk)
        _check_transition(locked, Scan.Status.FAILED)
        locked.status = Scan.Status.FAILED
        locked.error_message = user_message or GENERIC_FAILURE_MESSAGE
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "error_message", "completed_at"])
    return locked


RETENTION_EXEMPT_SESSION_KEYS = ("demo-seed-session",)


def purge_expired_guest_scans(*, dry_run: bool = False, now=None) -> int:
    """
    Delete guest scans older than GUEST_SCAN_RETENTION_HOURS. Related images,
    identifications and estimates cascade; stored files are removed by the
    ScanImage post_delete signal after commit. Returns the number of scans.
    """
    cutoff = (now or timezone.now()) - timedelta(hours=settings.GUEST_SCAN_RETENTION_HOURS)
    expired = Scan.objects.filter(user__isnull=True, created_at__lt=cutoff).exclude(
        session_key__in=RETENTION_EXEMPT_SESSION_KEYS
    )
    count = expired.count()
    if dry_run or count == 0:
        return count
    with transaction.atomic():
        expired.delete()
        record_audit_event(
            action="scans.purged",
            target_type="Scan",
            target_id="guest",
            metadata={"count": count, "retention_hours": settings.GUEST_SCAN_RETENTION_HOURS},
        )
    logger.info("scans.purged count=%s", count)
    return count
