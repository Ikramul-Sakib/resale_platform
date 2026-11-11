"""
Cache-backed fixed-window rate limiting for scan uploads.

Uses Django's configured cache. The default LocMemCache is per-process;
production should configure a shared cache (e.g. Redis) so limits apply
across workers.
"""

from django.conf import settings
from django.core.cache import cache


def client_ip(request) -> str:
    """
    Client IP for rate limiting. X-Forwarded-For is only trusted for the
    configured number of reverse proxies, so clients cannot spoof it.
    """
    proxies = settings.RATE_LIMIT_TRUSTED_PROXY_COUNT
    if proxies > 0:
        hops = [h.strip() for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return request.META.get("REMOTE_ADDR", "")


def is_rate_limited(scope: str, ident: str, limit: int, window_seconds: int) -> bool:
    """Count one hit for (scope, ident); return True once the limit is exceeded."""
    key = f"ratelimit:{scope}:{ident}"
    if cache.add(key, 1, timeout=window_seconds):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window_seconds)
            count = 1
    return count > limit


def scan_upload_rate_limited(request) -> bool:
    return is_rate_limited(
        "scan-upload",
        client_ip(request),
        settings.SCAN_UPLOAD_IP_RATE_LIMIT,
        settings.SCAN_UPLOAD_IP_RATE_WINDOW_MINUTES * 60,
    )
