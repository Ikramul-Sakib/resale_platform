"""
Phase 5B tests — scan upload/status/result UI, private image view,
per-user/guest isolation, identification correction, per-IP throttling,
and expired guest scan purging.
"""

import io
import secrets
import shutil
import tempfile
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import AuditEvent
from apps.catalog.models import Brand, Category
from apps.scans import services as scan_services
from apps.scans.models import IdentifiedItem, Scan, ScanImage
from apps.scans.throttling import client_ip

User = get_user_model()
PASSWORD = f"Test-{secrets.token_urlsafe(12)}-9a"


def jpeg_with_gps(size=(64, 48)):
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def photo(name="item.jpg"):
    return SimpleUploadedFile(name, jpeg_with_gps(), content_type="image/jpeg")


class ScanUITestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self._media = tempfile.mkdtemp(prefix="valulens-test-media-")
        self._override = override_settings(MEDIA_ROOT=self._media, RECOGNITION_PROVIDER="mock")
        self._override.enable()
        self.owner = User.objects.create_user(email="owner@example.com", password=PASSWORD)
        self.other = User.objects.create_user(email="other@example.com", password=PASSWORD)

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().tearDown()

    def upload(self, client=None, file=None, **extra):
        client = client or self.client
        with self.captureOnCommitCallbacks(execute=True):
            return client.post(reverse("scans:upload"), {"image": file or photo()}, **extra)

    def make_completed_scan(self, user=None, session_key="", confidence="0.40", provider="MOCK"):
        scan = Scan.objects.create(
            user=user, session_key=session_key, status=Scan.Status.COMPLETED, completed_at=timezone.now()
        )
        IdentifiedItem.objects.create(
            scan=scan,
            category=Category.objects.get_or_create(slug="uncategorized", defaults={"name": "Uncategorized"})[0],
            title="MOCK result - not a real identification",
            condition=IdentifiedItem.Condition.UNKNOWN,
            confidence=Decimal(confidence),
            provider_name=provider,
        )
        return scan


# ═══════════════════════════════════════════════════════════════════════
# Upload
# ═══════════════════════════════════════════════════════════════════════


class TestUploadView(ScanUITestCase):
    def test_upload_page_renders_for_guest_with_retention_notice(self):
        response = self.client.get(reverse("scans:upload"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "scans/upload.html")
        self.assertContains(response, "scanning as a guest")
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_user_upload_processes_and_shows_mock_result(self):
        self.client.force_login(self.owner)
        response = self.upload()
        scan = Scan.objects.get()
        self.assertRedirects(response, reverse("scans:detail", args=[scan.public_id]))
        self.assertEqual(scan.user, self.owner)
        self.assertEqual(scan.status, Scan.Status.COMPLETED)  # eager Celery in dev/tests

        detail = self.client.get(response.url)
        self.assertContains(detail, "badge--mock")
        self.assertContains(detail, "MOCK result: no real image recognition was performed")
        self.assertContains(detail, reverse("scans:image", args=[scan.public_id]))
        self.assertNotContains(detail, 'http-equiv="refresh"')

    def test_guest_upload_creates_session_owned_scan(self):
        response = self.upload()
        scan = Scan.objects.get()
        self.assertIsNone(scan.user)
        self.assertEqual(scan.session_key, self.client.session.session_key)
        self.assertEqual(self.client.get(response.url).status_code, 200)
        self.assertContains(self.client.get(reverse("scans:history")), str(scan.public_id))

    def test_invalid_file_shows_safe_error_and_creates_nothing(self):
        bad = SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        response = self.upload(file=bad)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Unsupported file type", status_code=400)
        self.assertEqual(Scan.objects.count(), 0)

    def test_missing_file_rejected(self):
        response = self.client.post(reverse("scans:upload"), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Scan.objects.count(), 0)

    @override_settings(SCAN_UPLOAD_IP_RATE_LIMIT=1)
    def test_per_ip_rate_limit_returns_429(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.upload(REMOTE_ADDR="10.0.0.1").status_code, 302)
        limited = self.upload(REMOTE_ADDR="10.0.0.1")
        self.assertEqual(limited.status_code, 429)
        self.assertContains(limited, "Too many uploads", status_code=429)
        self.assertEqual(self.upload(REMOTE_ADDR="10.0.0.2").status_code, 302)
        self.assertEqual(Scan.objects.count(), 2)

    @override_settings(SCAN_UPLOAD_IP_RATE_LIMIT=1)
    def test_spoofed_forwarded_for_ignored_without_trusted_proxy(self):
        self.upload(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1")
        limited = self.upload(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="2.2.2.2")
        self.assertEqual(limited.status_code, 429)

    @override_settings(GUEST_SCAN_RATE_LIMIT=1)
    def test_guest_session_limit_returns_429(self):
        self.upload()
        response = self.upload()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "guest scan limit", status_code=429)


class TestClientIp(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_remote_addr_used_by_default(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="6.6.6.6")
        self.assertEqual(client_ip(request), "10.0.0.9")

    @override_settings(RATE_LIMIT_TRUSTED_PROXY_COUNT=1)
    def test_trusted_proxy_hop_used(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.5")
        self.assertEqual(client_ip(request), "203.0.113.5")


# ═══════════════════════════════════════════════════════════════════════
# Status / result states
# ═══════════════════════════════════════════════════════════════════════


class TestDetailStates(ScanUITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_in_progress_scan_auto_refreshes(self):
        scan = Scan.objects.create(user=self.owner, status=Scan.Status.PROCESSING)
        response = self.client.get(reverse("scans:detail", args=[scan.public_id]))
        self.assertContains(response, 'http-equiv="refresh"')
        self.assertContains(response, "Identifying your item")

    def test_failed_scan_shows_safe_message(self):
        scan = Scan.objects.create(
            user=self.owner, status=Scan.Status.FAILED, completed_at=timezone.now(),
            error_message="The recognition service took too long to respond.",
        )
        response = self.client.get(reverse("scans:detail", args=[scan.public_id]))
        self.assertContains(response, "took too long to respond")
        self.assertContains(response, "Try another photo")

    @override_settings(RECOGNITION_LOW_CONFIDENCE_THRESHOLD=Decimal("0.60"))
    def test_low_confidence_prompts_correction(self):
        scan = self.make_completed_scan(user=self.owner, confidence="0.40")
        response = self.client.get(reverse("scans:detail", args=[scan.public_id]))
        self.assertContains(response, "Low confidence")
        self.assertContains(response, "40%")

    def test_dashboard_links_recent_scans(self):
        scan = self.make_completed_scan(user=self.owner)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, reverse("scans:detail", args=[scan.public_id]))
        self.assertContains(response, "MOCK result - not a real identification")


# ═══════════════════════════════════════════════════════════════════════
# Object-level authorization
# ═══════════════════════════════════════════════════════════════════════


class TestScanIsolation(ScanUITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        self.upload()
        self.scan = Scan.objects.get()
        self.urls = [
            reverse("scans:detail", args=[self.scan.public_id]),
            reverse("scans:image", args=[self.scan.public_id]),
            reverse("scans:correct", args=[self.scan.public_id]),
        ]

    def test_owner_gets_private_sanitised_image(self):
        response = self.client.get(self.urls[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        body = b"".join(response.streaming_content)
        self.assertEqual(len(Image.open(io.BytesIO(body)).getexif()), 0)

    def test_other_user_gets_404_everywhere(self):
        self.client.force_login(self.other)
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(self.urls[2], {"title": "hijack"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("scans:history")), str(self.scan.public_id))

    def test_anonymous_gets_404_for_user_scan(self):
        self.client.logout()
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_guest_scan_hidden_from_other_sessions_and_users(self):
        guest = self.client_class()
        self.upload(client=guest)
        guest_scan = Scan.objects.get(user__isnull=True)
        url = reverse("scans:image", args=[guest_scan.public_id])
        self.assertEqual(guest.get(url).status_code, 200)
        self.assertEqual(self.client_class().get(url).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 404)  # logged-in owner of other scans

    def test_unknown_scan_is_404(self):
        import uuid

        self.assertEqual(self.client.get(reverse("scans:detail", args=[uuid.uuid4()])).status_code, 404)

    def test_guest_scan_claimed_on_login_becomes_accessible(self):
        guest = self.client_class()
        self.upload(client=guest)
        guest_scan = Scan.objects.get(user__isnull=True)
        guest.post(reverse("accounts:login"), {"email": "other@example.com", "password": PASSWORD})
        self.assertEqual(guest.get(reverse("scans:detail", args=[guest_scan.public_id])).status_code, 200)


# ═══════════════════════════════════════════════════════════════════════
# Correction
# ═══════════════════════════════════════════════════════════════════════


class TestCorrection(ScanUITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        self.scan = self.make_completed_scan(user=self.owner)
        self.sneakers = Category.objects.create(name="Sneakers")
        self.brand = Brand.objects.create(name="Acme")
        self.url = reverse("scans:correct", args=[self.scan.public_id])

    def payload(self, title="Acme Runner"):
        return {
            "title": title, "category": self.sneakers.pk, "brand": self.brand.pk,
            "model_name": "AR-1", "condition": "good",
        }

    def test_correction_saved_as_manual_and_keeps_provider_original(self):
        response = self.client.post(self.url, self.payload())
        self.assertRedirects(response, reverse("scans:detail", args=[self.scan.public_id]))
        item = IdentifiedItem.objects.get(scan=self.scan)
        self.assertTrue(item.is_user_corrected)
        self.assertEqual((item.title, item.category, item.brand), ("Acme Runner", self.sneakers, self.brand))
        original = item.attributes["provider_original"]
        self.assertEqual(original["title"], "MOCK result - not a real identification")
        self.assertEqual(original["condition"], "unknown")
        self.assertTrue(AuditEvent.objects.filter(action="identified_item.corrected", actor=self.owner).exists())
        self.assertContains(self.client.get(response.url), "Corrected by you")

    def test_corrected_mock_scan_keeps_provenance_labels_in_lists(self):
        self.client.post(self.url, self.payload())
        for url in (reverse("accounts:dashboard"), reverse("scans:history")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "Acme Runner")
                self.assertContains(response, '<span class="badge badge--mock">MOCK</span>', html=True)
                self.assertContains(response, '<span class="badge badge--manual">Corrected</span>', html=True)

    def test_second_correction_preserves_first_original(self):
        self.client.post(self.url, self.payload("First"))
        self.client.post(self.url, self.payload("Second"))
        item = IdentifiedItem.objects.get(scan=self.scan)
        self.assertEqual(item.title, "Second")
        self.assertEqual(item.attributes["provider_original"]["title"], "MOCK result - not a real identification")

    def test_invalid_correction_rejected(self):
        response = self.client.post(self.url, {**self.payload(), "title": "", "condition": "mint"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(IdentifiedItem.objects.get(scan=self.scan).is_user_corrected)

    def test_cannot_correct_incomplete_scan(self):
        scan = Scan.objects.create(user=self.owner)
        self.assertEqual(self.client.get(reverse("scans:correct", args=[scan.public_id])).status_code, 404)


# ═══════════════════════════════════════════════════════════════════════
# History
# ═══════════════════════════════════════════════════════════════════════


class TestHistory(ScanUITestCase):
    def test_empty_state(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("scans:history")), "No scans yet")

    def test_paginated_and_scoped_to_user(self):
        for _ in range(12):
            Scan.objects.create(user=self.owner)
        Scan.objects.create(user=self.other)
        self.client.force_login(self.owner)
        page1 = self.client.get(reverse("scans:history"))
        page2 = self.client.get(reverse("scans:history"), {"page": 2})
        self.assertEqual(len(page1.context["scans"]), 10)
        self.assertEqual(len(page2.context["scans"]), 2)
        self.assertTrue(all(s.user == self.owner for s in list(page1.context["scans"]) + list(page2.context["scans"])))


# ═══════════════════════════════════════════════════════════════════════
# Retention & file cleanup
# ═══════════════════════════════════════════════════════════════════════


@override_settings(GUEST_SCAN_RETENTION_HOURS=24)
class TestPurge(ScanUITestCase):
    def age(self, scan, hours):
        Scan.objects.filter(pk=scan.pk).update(created_at=timezone.now() - timedelta(hours=hours))

    def guest_scan(self):
        with mock.patch.object(scan_services, "enqueue_scan"):
            return scan_services.create_scan(photo(), session_key="g" * 32)

    def test_purges_only_expired_guest_scans_and_their_files(self):
        old_guest = self.guest_scan()
        new_guest = self.guest_scan()
        with mock.patch.object(scan_services, "enqueue_scan"):
            old_user = scan_services.create_scan(photo(), user=self.owner)
        demo = Scan.objects.create(session_key="demo-seed-session")
        for scan in (old_guest, old_user, demo):
            self.age(scan, 48)
        old_key = old_guest.images.get().storage_key

        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("purge_expired_scans", stdout=out)

        self.assertIn("Deleted 1 guest scan(s) older than 24h.", out.getvalue())
        self.assertFalse(Scan.objects.filter(pk=old_guest.pk).exists())
        self.assertFalse(default_storage.exists(old_key))
        for kept in (new_guest, old_user, demo):
            self.assertTrue(Scan.objects.filter(pk=kept.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action="scans.purged").exists())

    def test_dry_run_deletes_nothing(self):
        scan = self.guest_scan()
        self.age(scan, 48)
        out = io.StringIO()
        call_command("purge_expired_scans", "--dry-run", stdout=out)
        self.assertIn("Would delete 1", out.getvalue())
        self.assertTrue(Scan.objects.filter(pk=scan.pk).exists())

    def test_account_deletion_removes_stored_images(self):
        with mock.patch.object(scan_services, "enqueue_scan"):
            scan = scan_services.create_scan(photo(), user=self.owner)
        key = scan.images.get().storage_key
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertFalse(ScanImage.objects.exists())
        self.assertFalse(default_storage.exists(key))


@override_settings(GUEST_SCAN_RETENTION_HOURS=24)
class TestPurgeClaimRace(TransactionTestCase):
    """Purge must not delete a scan whose row is locked by a concurrent claim."""

    def test_purge_skips_scan_locked_by_in_flight_claim(self):
        user = User.objects.create_user(email="claimer@example.com", password=PASSWORD)
        scan = Scan.objects.create(session_key="c" * 32)
        Scan.objects.filter(pk=scan.pk).update(created_at=timezone.now() - timedelta(hours=48))

        locked, release, done = threading.Event(), threading.Event(), threading.Event()

        def claim_in_other_connection():
            try:
                with transaction.atomic():
                    Scan.objects.select_for_update().filter(pk=scan.pk).update(user=user, session_key="")
                    locked.set()
                    release.wait(timeout=10)
            finally:
                connection.close()
                done.set()

        worker = threading.Thread(target=claim_in_other_connection)
        worker.start()
        self.assertTrue(locked.wait(timeout=10))
        try:
            self.assertEqual(scan_services.purge_expired_guest_scans(), 0)
        finally:
            release.set()
            worker.join(timeout=10)
        self.assertTrue(done.is_set())

        scan.refresh_from_db()
        self.assertEqual(scan.user, user)
        self.assertEqual(scan_services.purge_expired_guest_scans(), 0)
        self.assertTrue(Scan.objects.filter(pk=scan.pk).exists())
