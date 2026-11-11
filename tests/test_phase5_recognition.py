"""
Phase 5A tests — upload validation, recognition providers, scan lifecycle,
and the Celery recognition task.
"""

import io
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.accounts.models import AuditEvent
from apps.catalog.models import Brand, Category
from apps.recognition import services as recognition_services
from apps.recognition.exceptions import (
    CorruptImageError,
    ImageTooLargeError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RecognitionNotConfiguredError,
    UnsupportedImageTypeError,
)
from apps.recognition.images import validate_and_sanitize
from apps.recognition.providers import RecognitionProvider, RecognitionResult, get_provider
from apps.recognition.providers.mock import MockRecognitionProvider
from apps.scans import services as scan_services
from apps.scans.models import IdentifiedItem, Scan, ScanImage
from apps.scans.tasks import process_scan, retry_countdown

User = get_user_model()

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def make_image_bytes(fmt="JPEG", size=(64, 48), color=(200, 30, 30), exif=None, mode="RGB"):
    buffer = io.BytesIO()
    image = Image.new(mode, size, color)
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def make_exif_with_gps(orientation=None):
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    exif[GPS_IFD] = {1: "N", 2: (51.0, 30.0, 0.0), 3: "W", 4: (0.0, 7.0, 0.0)}
    if orientation:
        exif[ORIENTATION] = orientation
    return exif


def upload(data, name="photo.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


class TempMediaMixin:
    def setUp(self):
        super().setUp()
        self._media = tempfile.mkdtemp(prefix="valulens-test-media-")
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().tearDown()


# ═══════════════════════════════════════════════════════════════════════
# Upload validation & sanitisation
# ═══════════════════════════════════════════════════════════════════════


class TestImageValidation(TestCase):
    def test_jpeg_exif_and_gps_are_stripped(self):
        data = make_image_bytes(exif=make_exif_with_gps())
        self.assertIn(GPS_IFD, Image.open(io.BytesIO(data)).getexif())

        result = validate_and_sanitize(upload(data))

        cleaned = Image.open(io.BytesIO(result.content))
        self.assertEqual(len(cleaned.getexif()), 0)
        self.assertNotIn("exif", cleaned.info)
        self.assertNotIn(b"SecretCameraMaker", result.content)
        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.extension, "jpg")
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(result.size, len(result.content))

    def test_exif_orientation_applied_before_stripping(self):
        data = make_image_bytes(size=(80, 40), exif=make_exif_with_gps(orientation=6))
        result = validate_and_sanitize(upload(data))
        self.assertEqual((result.width, result.height), (40, 80))

    def test_png_and_webp_accepted(self):
        for fmt, mime in (("PNG", "image/png"), ("WEBP", "image/webp")):
            with self.subTest(fmt=fmt):
                result = validate_and_sanitize(upload(make_image_bytes(fmt=fmt)))
                self.assertEqual(result.content_type, mime)
                self.assertEqual(Image.open(io.BytesIO(result.content)).format, fmt)

    def test_real_format_detected_regardless_of_declared_type(self):
        data = make_image_bytes(fmt="PNG")
        result = validate_and_sanitize(upload(data, name="photo.jpg", content_type="image/jpeg"))
        self.assertEqual(result.content_type, "image/png")

    def test_gif_rejected_as_unsupported(self):
        data = make_image_bytes(fmt="GIF", mode="P", color=1)
        with self.assertRaises(UnsupportedImageTypeError):
            validate_and_sanitize(upload(data, name="a.gif", content_type="image/gif"))

    @override_settings(ALLOWED_IMAGE_TYPES=["image/jpeg"])
    def test_allowlist_setting_enforced(self):
        with self.assertRaises(UnsupportedImageTypeError):
            validate_and_sanitize(upload(make_image_bytes(fmt="PNG")))

    def test_non_image_rejected(self):
        with self.assertRaises(UnsupportedImageTypeError):
            validate_and_sanitize(upload(b"%PDF-1.4 not an image", name="x.jpg"))

    def test_truncated_image_rejected(self):
        data = make_image_bytes(size=(400, 400))
        with self.assertRaises(CorruptImageError):
            validate_and_sanitize(upload(data[: len(data) // 2]))

    def test_empty_file_rejected(self):
        with self.assertRaises(CorruptImageError):
            validate_and_sanitize(upload(b""))

    @override_settings(MAX_UPLOAD_SIZE_BYTES=1024)
    def test_oversize_file_rejected(self):
        with self.assertRaises(ImageTooLargeError):
            validate_and_sanitize(upload(b"\x00" * 2048))
        with self.assertRaises(ImageTooLargeError):
            validate_and_sanitize(io.BytesIO(b"\x00" * 2048))  # no declared size

    @override_settings(MAX_IMAGE_PIXELS=100)
    def test_decompression_bomb_rejected(self):
        with self.assertRaises(ImageTooLargeError):
            validate_and_sanitize(upload(make_image_bytes(size=(200, 200))))


# ═══════════════════════════════════════════════════════════════════════
# Provider registry & MOCK provider
# ═══════════════════════════════════════════════════════════════════════


class StubProvider(RecognitionProvider):
    name = "stub"

    def recognize(self, image_bytes, content_type, *, timeout):
        return RecognitionResult(title="Stub item", confidence=Decimal("0.9"))


class TestProviderRegistry(TestCase):
    @override_settings(RECOGNITION_PROVIDER="mock")
    def test_mock_selected(self):
        self.assertIsInstance(get_provider(), MockRecognitionProvider)

    @override_settings(RECOGNITION_PROVIDER="")
    def test_empty_setting_means_not_configured(self):
        with self.assertRaises(RecognitionNotConfiguredError):
            get_provider()

    @override_settings(RECOGNITION_PROVIDER="does-not-exist")
    def test_unknown_name_is_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            get_provider()

    @override_settings(RECOGNITION_PROVIDER="tests.test_phase5_recognition.StubProvider")
    def test_dotted_path_provider(self):
        self.assertIsInstance(get_provider(), StubProvider)

    @override_settings(RECOGNITION_PROVIDER="apps.scans.models.Scan")
    def test_dotted_path_must_be_provider_subclass(self):
        with self.assertRaises(ImproperlyConfigured):
            get_provider()


class TestMockProvider(TestCase):
    def test_result_is_labelled_mock_and_deterministic(self):
        data = make_image_bytes()
        provider = MockRecognitionProvider()
        first = provider.recognize(data, "image/jpeg", timeout=5)
        second = provider.recognize(data, "image/jpeg", timeout=5)

        self.assertEqual(provider.name, "MOCK")
        self.assertTrue(provider.is_mock)
        self.assertIn("MOCK", first.title)
        self.assertTrue(first.attributes["mock"])
        self.assertEqual(first, second)
        self.assertTrue(Decimal("0.30") <= first.confidence <= Decimal("0.95"))
        # Never fabricates brand/model/condition.
        self.assertIsNone(first.brand_name)
        self.assertIsNone(first.model_name)
        self.assertIsNone(first.condition)


class TestBuildIdentifiedItem(TestCase):
    def setUp(self):
        self.scan = Scan.objects.create(session_key="s" * 32)

    def test_mock_result_normalised(self):
        provider = MockRecognitionProvider()
        result = provider.recognize(make_image_bytes(), "image/jpeg", timeout=5)
        item = recognition_services.build_identified_item(self.scan, provider, result)

        self.assertEqual(item.provider_name, "MOCK")
        self.assertTrue(item.is_mock)
        self.assertTrue(item.attributes["mock"])
        self.assertEqual(item.condition, IdentifiedItem.Condition.UNKNOWN)
        self.assertEqual(item.category.slug, "uncategorized")
        self.assertIsNone(item.brand)

    def test_known_category_and_brand_matched_unknown_brand_not_created(self):
        Category.objects.create(name="Sneakers")
        Brand.objects.create(name="Acme")
        result = RecognitionResult(
            title="  Runner  ", confidence=0.876, category_slug="Sneakers", brand_name="acme",
            condition="excellent", color="Red",
        )
        item = recognition_services.build_identified_item(self.scan, StubProvider(), result)
        self.assertEqual(item.category.slug, "sneakers")
        self.assertEqual(item.brand.name, "Acme")
        self.assertEqual(item.title, "Runner")
        self.assertEqual(item.confidence, Decimal("0.88"))
        self.assertEqual(item.condition, "excellent")
        self.assertEqual(item.attributes["color"], "Red")

        brands_before = Brand.objects.count()
        other = RecognitionResult(title="X", confidence=0.5, brand_name="NoSuchBrand", condition="mint")
        item = recognition_services.build_identified_item(self.scan, StubProvider(), other)
        self.assertIsNone(item.brand)
        self.assertEqual(item.attributes["provider_brand"], "NoSuchBrand")
        self.assertEqual(item.condition, IdentifiedItem.Condition.UNKNOWN)
        self.assertEqual(item.attributes["provider_condition"], "mint")
        self.assertEqual(Brand.objects.count(), brands_before)

    def test_invalid_provider_output_rejected(self):
        for bad in (
            RecognitionResult(title="X", confidence=Decimal("1.5")),
            RecognitionResult(title="X", confidence=float("nan")),
            RecognitionResult(title="X", confidence="abc"),
            RecognitionResult(title="   ", confidence=0.5),
            RecognitionResult(title="X", confidence=0.5, attributes={"weight": Decimal("1.2")}),
        ):
            with self.subTest(result=bad), self.assertRaises(ProviderError):
                recognition_services.build_identified_item(self.scan, StubProvider(), bad)

    @override_settings(RECOGNITION_LOW_CONFIDENCE_THRESHOLD=Decimal("0.60"))
    def test_low_confidence_flag(self):
        low = recognition_services.build_identified_item(
            self.scan, StubProvider(), RecognitionResult(title="X", confidence=0.59)
        )
        high = recognition_services.build_identified_item(
            self.scan, StubProvider(), RecognitionResult(title="X", confidence=0.60)
        )
        self.assertTrue(low.is_low_confidence)
        self.assertFalse(high.is_low_confidence)


# ═══════════════════════════════════════════════════════════════════════
# Scan creation (users and guests)
# ═══════════════════════════════════════════════════════════════════════


class TestCreateScan(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(email="owner@example.com", password="Pass12345!x")

    def test_user_scan_created_with_sanitised_private_image(self):
        data = make_image_bytes(exif=make_exif_with_gps())
        with mock.patch.object(scan_services, "enqueue_scan") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                scan = scan_services.create_scan(upload(data), user=self.user)

        enqueue.assert_called_once_with(scan.pk)
        self.assertEqual(scan.user, self.user)
        self.assertEqual(scan.session_key, "")
        self.assertEqual(scan.status, Scan.Status.PENDING)

        image = scan.images.get()
        self.assertTrue(image.storage_key.startswith(f"scans/{scan.public_id}/"))
        with default_storage.open(image.storage_key, "rb") as fh:
            stored = fh.read()
        self.assertEqual(len(Image.open(io.BytesIO(stored)).getexif()), 0)
        self.assertEqual(image.file_size, len(stored))
        self.assertTrue(
            AuditEvent.objects.filter(action="scan.created", target_id=str(scan.public_id)).exists()
        )

    def test_guest_scan_uses_session_key(self):
        with mock.patch.object(scan_services, "enqueue_scan"):
            scan = scan_services.create_scan(upload(make_image_bytes()), session_key="g" * 32)
        self.assertIsNone(scan.user)
        self.assertEqual(scan.session_key, "g" * 32)

    def test_guest_scan_requires_session_key(self):
        with self.assertRaises(ValueError):
            scan_services.create_scan(upload(make_image_bytes()))
        self.assertEqual(Scan.objects.count(), 0)

    @override_settings(GUEST_SCAN_RATE_LIMIT=2)
    def test_guest_rate_limit_enforced_per_session(self):
        with mock.patch.object(scan_services, "enqueue_scan"):
            for _ in range(2):
                scan_services.create_scan(upload(make_image_bytes()), session_key="a" * 32)
            with self.assertRaises(scan_services.GuestScanLimitExceeded):
                scan_services.create_scan(upload(make_image_bytes()), session_key="a" * 32)
            # Another session and authenticated users are unaffected.
            scan_services.create_scan(upload(make_image_bytes()), session_key="b" * 32)
            scan_services.create_scan(upload(make_image_bytes()), user=self.user)
        self.assertEqual(Scan.objects.count(), 4)

    def test_invalid_upload_creates_no_scan_and_no_file(self):
        with self.assertRaises(UnsupportedImageTypeError):
            scan_services.create_scan(upload(b"not an image"), user=self.user)
        self.assertEqual(Scan.objects.count(), 0)
        self.assertEqual(ScanImage.objects.count(), 0)
        self.assertEqual(default_storage.listdir(""), ([], []))

    def test_enqueue_failure_after_commit_keeps_scan_and_file(self):
        with mock.patch.object(scan_services, "enqueue_scan", side_effect=ConnectionError("broker down")):
            with self.assertLogs("django", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    scan = scan_services.create_scan(upload(make_image_bytes()), user=self.user)
        self.assertEqual(Scan.objects.get().status, Scan.Status.PENDING)
        self.assertTrue(default_storage.exists(scan.images.get().storage_key))

    def test_stored_file_removed_if_db_write_fails(self):
        with mock.patch.object(ScanImage.objects, "create", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                scan_services.create_scan(upload(make_image_bytes()), user=self.user)
        self.assertEqual(Scan.objects.count(), 0)
        self.assertEqual(default_storage.listdir("scans")[1], [])


# ═══════════════════════════════════════════════════════════════════════
# Status transitions
# ═══════════════════════════════════════════════════════════════════════


class TestScanTransitions(TestCase):
    def test_terminal_states_are_final(self):
        scan = Scan.objects.create(session_key="t" * 32)
        scan_services.fail_scan(scan, "bad")
        self.assertIsNone(scan_services.start_processing(scan.pk))
        with self.assertRaises(scan_services.InvalidScanTransition):
            scan_services.fail_scan(scan, "again")

    def test_pending_to_processing_to_failed_sets_completed_at(self):
        scan = Scan.objects.create(session_key="t" * 32)
        scan = scan_services.start_processing(scan.pk)
        self.assertEqual(scan.status, Scan.Status.PROCESSING)
        self.assertIsNone(scan.completed_at)
        scan = scan_services.fail_scan(scan, "Safe message")
        self.assertEqual(scan.status, Scan.Status.FAILED)
        self.assertEqual(scan.error_message, "Safe message")
        self.assertIsNotNone(scan.completed_at)

    def test_pending_cannot_complete_directly(self):
        scan = Scan.objects.create(session_key="t" * 32)
        item = IdentifiedItem(
            category=Category.objects.create(name="Misc"), title="x",
            confidence=Decimal("0.5"), provider_name="stub",
        )
        with self.assertRaises(scan_services.InvalidScanTransition):
            scan_services.complete_scan(scan, item)
        self.assertFalse(IdentifiedItem.objects.exists())


# ═══════════════════════════════════════════════════════════════════════
# Celery task: end-to-end, retries, failures
# ═══════════════════════════════════════════════════════════════════════


@override_settings(
    RECOGNITION_PROVIDER="mock",
    RECOGNITION_MAX_RETRIES=2,
    RECOGNITION_RETRY_BACKOFF_SECONDS=1,
    RECOGNITION_RETRY_BACKOFF_MAX_SECONDS=3,
)
class TestProcessScanTask(TempMediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        with mock.patch.object(scan_services, "enqueue_scan"):
            self.scan = scan_services.create_scan(upload(make_image_bytes()), session_key="k" * 32)

    def run_task(self):
        return process_scan.apply(args=[self.scan.pk])

    def test_mock_end_to_end_completes_with_mock_label(self):
        with self.assertLogs("apps.recognition.services", level="INFO") as logs:
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.COMPLETED)
        self.assertIsNotNone(self.scan.completed_at)
        item = self.scan.identified_item
        self.assertEqual(item.provider_name, "MOCK")
        self.assertTrue(item.attributes["mock"])
        self.assertTrue(any("[MOCK]" in line for line in logs.output))

    def test_task_is_idempotent(self):
        self.run_task()
        self.run_task()
        self.assertEqual(IdentifiedItem.objects.filter(scan=self.scan).count(), 1)

    def test_missing_scan_is_noop(self):
        self.assertIsNone(process_scan.apply(args=[999999]).result)

    def test_transient_error_retried_then_succeeds(self):
        real = MockRecognitionProvider.recognize
        calls = {"n": 0}

        def flaky(provider, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ProviderTimeoutError("slow")
            return real(provider, *args, **kwargs)

        with mock.patch.object(MockRecognitionProvider, "recognize", flaky):
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(calls["n"], 2)
        self.assertEqual(self.scan.status, Scan.Status.COMPLETED)

    def test_builtin_timeout_treated_as_retryable(self):
        with mock.patch.object(MockRecognitionProvider, "recognize", side_effect=TimeoutError) as rec:
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(rec.call_count, 3)
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, ProviderTimeoutError.user_message)

    def test_retries_are_bounded_then_scan_fails_with_safe_message(self):
        with mock.patch.object(
            MockRecognitionProvider, "recognize",
            side_effect=ProviderUnavailableError("upstream 503 secret-host-detail"),
        ) as rec:
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(rec.call_count, 3)  # 1 attempt + RECOGNITION_MAX_RETRIES
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, ProviderUnavailableError.user_message)
        self.assertNotIn("secret-host-detail", self.scan.error_message)

    def test_permanent_provider_error_not_retried(self):
        with mock.patch.object(MockRecognitionProvider, "recognize", side_effect=ProviderError("bad")) as rec:
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(rec.call_count, 1)
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, ProviderError.user_message)

    def test_invalid_provider_output_fails_scan(self):
        bad = RecognitionResult(title="X", confidence=Decimal("7"))
        with mock.patch.object(MockRecognitionProvider, "recognize", return_value=bad):
            self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertFalse(IdentifiedItem.objects.filter(scan=self.scan).exists())

    def test_not_configured_fails_without_pretending(self):
        for value, in (("",), ("nope",)):
            with self.subTest(value=value):
                scan = Scan.objects.create(session_key="n" * 32)
                with override_settings(RECOGNITION_PROVIDER=value):
                    process_scan.apply(args=[scan.pk])
                scan.refresh_from_db()
                self.assertEqual(scan.status, Scan.Status.FAILED)
                self.assertEqual(scan.error_message, RecognitionNotConfiguredError.user_message)
                self.assertFalse(IdentifiedItem.objects.filter(scan=scan).exists())

    def test_unexpected_exception_fails_with_generic_message(self):
        with mock.patch.object(MockRecognitionProvider, "recognize", side_effect=KeyError("internal")):
            with self.assertLogs("apps.scans.tasks", level="ERROR"):
                self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, scan_services.GENERIC_FAILURE_MESSAGE)

    def test_persistence_error_fails_scan_instead_of_leaving_it_processing(self):
        with mock.patch.object(scan_services, "complete_scan", side_effect=RuntimeError("db error")):
            with self.assertLogs("apps.scans.tasks", level="ERROR"):
                self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, scan_services.GENERIC_FAILURE_MESSAGE)

    def test_missing_stored_image_fails_scan(self):
        default_storage.delete(self.scan.images.get().storage_key)
        self.run_task()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.FAILED)
        self.assertEqual(self.scan.error_message, "The uploaded image is no longer available.")

    def test_worker_mode_schedules_retry_with_backoff(self):
        with mock.patch.object(MockRecognitionProvider, "recognize", side_effect=ProviderTimeoutError("slow")):
            with mock.patch.object(process_scan, "retry", side_effect=Retry()) as retry:
                with self.assertRaises(Retry):
                    process_scan(self.scan.pk)  # direct call: not eager
        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs["countdown"], 1)
        self.assertEqual(retry.call_args.kwargs["max_retries"], 2)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, Scan.Status.PROCESSING)

    def test_retry_countdown_is_exponential_and_capped(self):
        self.assertEqual([retry_countdown(n) for n in range(4)], [1, 2, 3, 3])
