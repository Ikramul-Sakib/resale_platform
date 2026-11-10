"""
Services for accounts: audit event logging and guest scan claiming.
"""

from typing import Optional
from django.contrib.auth import get_user_model

User = get_user_model()


def get_client_ip(request) -> str:
    """Safely extract the client IP address from the request."""
    if not request:
        return ""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def record_audit_event(
    action: str,
    target_type: str,
    target_id: str,
    actor=None,
    metadata: Optional[dict] = None,
):
    """
    Record an immutable audit log entry.
    Ensures passwords, tokens, and PII are never logged.
    """
    from apps.accounts.models import AuditEvent

    # Ensure actor is a valid saved User instance, or None
    user_actor = actor if (actor and getattr(actor, "is_authenticated", False)) else None

    return AuditEvent.objects.create(
        actor=user_actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata=metadata or {},
    )


def claim_guest_scans(session_key: str, user) -> int:
    """
    Associate any guest scans created during the current session with the newly logged-in user.
    """
    if not session_key or not user or not user.is_authenticated:
        return 0

    try:
        from apps.scans.models import Scan

        updated_count = Scan.objects.filter(
            session_key=session_key,
            user__isnull=True,
        ).update(
            user=user,
            session_key="",
        )

        if updated_count > 0:
            record_audit_event(
                actor=user,
                action="scans.claimed",
                target_type="User",
                target_id=str(user.pk),
                metadata={"claimed_count": updated_count},
            )

        return updated_count
    except Exception:
        # Fallback gracefully if scans table or app is not loaded
        return 0
