"""
Phase 3 tests — Catalog, Scans, and Pricing models.

Tests cover:
- CRUD operations
- DB constraints (CHECK, UNIQUE, FK, PROTECT, SET_NULL)
- Edge cases (boundary values, blank fields, JSONB)
- Seed data verification
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Brand, Category
from apps.pricing.models import MarketPriceObservation, PriceEstimate
from apps.scans.models import IdentifiedItem, Scan, ScanImage


# ═══════════════════════════════════════════════════════════════════════
# Category tests
# ═══════════════════════════════════════════════════════════════════════


class TestCategoryModel(TestCase):
    """Tests for the Category model."""

    def test_create_category(self):
        cat = Category.objects.create(name="Test Category", description="A test.")
        self.assertEqual(cat.name, "Test Category")
        self.assertEqual(cat.slug, "test-category")
        self.assertIsNotNone(cat.created_at)

    def test_slug_auto_generated(self):
        cat = Category.objects.create(name="My Fancy Category")
        self.assertEqual(cat.slug, "my-fancy-category")

    def test_explicit_slug_not_overridden(self):
        cat = Category.objects.create(name="Custom", slug="my-custom-slug")
        self.assertEqual(cat.slug, "my-custom-slug")

    def test_unique_name(self):
        Category.objects.create(name="Unique Cat")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name="Unique Cat")

    def test_unique_slug(self):
        Category.objects.create(name="A", slug="same-slug")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name="B", slug="same-slug")

    def test_str(self):
        cat = Category.objects.create(name="Sneakers")
        self.assertEqual(str(cat), "Sneakers")

    def test_ordering(self):
        Category.objects.create(name="Zebra")
        Category.objects.create(name="Apple")
        names = list(Category.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))


# ═══════════════════════════════════════════════════════════════════════
# Brand tests
# ═══════════════════════════════════════════════════════════════════════


class TestBrandModel(TestCase):
    """Tests for the Brand model."""

    def test_create_brand(self):
        brand = Brand.objects.create(name="Test Brand")
        self.assertEqual(brand.slug, "test-brand")

    def test_unique_name(self):
        Brand.objects.create(name="OnlyOne")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Brand.objects.create(name="OnlyOne")

    def test_str(self):
        brand = Brand.objects.create(name="Cool Brand")
        self.assertEqual(str(brand), "Cool Brand")


# ═══════════════════════════════════════════════════════════════════════
# Scan tests
# ═══════════════════════════════════════════════════════════════════════


class TestScanModel(TestCase):
    """Tests for the Scan model."""

    def test_create_guest_scan(self):
        scan = Scan.objects.create(session_key="abc12345")
        self.assertIsNone(scan.user)
        self.assertEqual(scan.status, Scan.Status.PENDING)
        self.assertIsNotNone(scan.public_id)
        self.assertIsNone(scan.completed_at)

    def test_create_authenticated_scan(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(
            email="scanner@test.dev", password="Pass123!"
        )
        scan = Scan.objects.create(user=user)
        self.assertEqual(scan.user, user)

    def test_completed_at_constraint_valid(self):
        """completed_at is allowed when status is completed."""
        scan = Scan.objects.create(
            session_key="test",
            status=Scan.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.assertIsNotNone(scan.completed_at)

    def test_completed_at_constraint_failed_valid(self):
        """completed_at is allowed when status is failed."""
        scan = Scan.objects.create(
            session_key="test",
            status=Scan.Status.FAILED,
            completed_at=timezone.now(),
            error_message="Something went wrong",
        )
        self.assertIsNotNone(scan.completed_at)

    def test_completed_at_constraint_violation(self):
        """completed_at must be NULL when status is pending or processing."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Scan.objects.create(
                    session_key="test",
                    status=Scan.Status.PENDING,
                    completed_at=timezone.now(),
                )

    def test_completed_at_constraint_processing_violation(self):
        """completed_at must be NULL when status is processing."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Scan.objects.create(
                    session_key="test",
                    status=Scan.Status.PROCESSING,
                    completed_at=timezone.now(),
                )

    def test_null_completed_at_allowed_for_completed(self):
        """NULL completed_at is technically allowed for completed (constraint is one-way)."""
        # The CHECK allows completed_at=NULL for any status.
        # Business logic in the service layer should set it, but the DB allows it.
        scan = Scan.objects.create(
            session_key="test",
            status=Scan.Status.COMPLETED,
        )
        self.assertIsNone(scan.completed_at)

    def test_cascade_on_user_delete(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(
            email="del@test.dev", password="Pass123!"
        )
        Scan.objects.create(user=user)
        user_pk = user.pk
        self.assertEqual(Scan.objects.filter(user_id=user_pk).count(), 1)
        user.delete()
        self.assertEqual(Scan.objects.filter(user_id=user_pk).count(), 0)

    def test_str_format(self):
        scan = Scan.objects.create(session_key="abcdefghij")
        self.assertIn("guest:", str(scan))
        self.assertIn("pending", str(scan))


# ═══════════════════════════════════════════════════════════════════════
# ScanImage tests
# ═══════════════════════════════════════════════════════════════════════


class TestScanImageModel(TestCase):
    """Tests for the ScanImage model."""

    def setUp(self):
        self.scan = Scan.objects.create(session_key="img-test")

    def test_create_scan_image(self):
        img = ScanImage.objects.create(
            scan=self.scan,
            storage_key="scans/test/image1.jpg",
            content_type="image/jpeg",
            file_size=204800,
            sha256="a" * 64,
        )
        self.assertEqual(img.content_type, "image/jpeg")
        self.assertEqual(img.file_size, 204800)

    def test_cascade_on_scan_delete(self):
        ScanImage.objects.create(
            scan=self.scan,
            storage_key="scans/test/image2.jpg",
            content_type="image/png",
            file_size=102400,
            sha256="b" * 64,
        )
        self.assertEqual(ScanImage.objects.count(), 1)
        self.scan.delete()
        self.assertEqual(ScanImage.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════
# IdentifiedItem tests
# ═══════════════════════════════════════════════════════════════════════


class TestIdentifiedItemModel(TestCase):
    """Tests for the IdentifiedItem model."""

    def setUp(self):
        self.category = Category.objects.create(name="Test Cat")
        self.brand = Brand.objects.create(name="Test Brand")
        self.scan = Scan.objects.create(
            session_key="id-test",
            status=Scan.Status.COMPLETED,
            completed_at=timezone.now(),
        )

    def test_create_identified_item(self):
        item = IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            brand=self.brand,
            title="Test Item",
            model_name="TI-001",
            condition=IdentifiedItem.Condition.EXCELLENT,
            attributes={"color": "blue", "size": "M"},
            confidence=Decimal("0.92"),
            provider_name="mock",
        )
        self.assertEqual(item.title, "Test Item")
        self.assertEqual(item.confidence, Decimal("0.92"))
        self.assertFalse(item.is_user_corrected)

    def test_confidence_range_check_lower_bound(self):
        """Confidence below 0 violates the CHECK constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IdentifiedItem.objects.create(
                    scan=self.scan,
                    category=self.category,
                    title="Bad Confidence",
                    confidence=Decimal("-0.01"),
                    provider_name="mock",
                )

    def test_confidence_range_check_upper_bound(self):
        """Confidence above 1 violates the CHECK constraint."""
        scan2 = Scan.objects.create(session_key="id-test-2")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IdentifiedItem.objects.create(
                    scan=scan2,
                    category=self.category,
                    title="Bad Confidence",
                    confidence=Decimal("1.01"),
                    provider_name="mock",
                )

    def test_confidence_boundary_zero(self):
        """Confidence of exactly 0 is valid."""
        scan2 = Scan.objects.create(session_key="id-test-zero")
        item = IdentifiedItem.objects.create(
            scan=scan2,
            category=self.category,
            title="Zero Confidence",
            confidence=Decimal("0.00"),
            provider_name="mock",
        )
        self.assertEqual(item.confidence, Decimal("0.00"))

    def test_confidence_boundary_one(self):
        """Confidence of exactly 1 is valid."""
        scan2 = Scan.objects.create(session_key="id-test-one")
        item = IdentifiedItem.objects.create(
            scan=scan2,
            category=self.category,
            title="Full Confidence",
            confidence=Decimal("1.00"),
            provider_name="mock",
        )
        self.assertEqual(item.confidence, Decimal("1.00"))

    def test_brand_nullable(self):
        """Items can exist without a brand."""
        scan2 = Scan.objects.create(session_key="no-brand")
        item = IdentifiedItem.objects.create(
            scan=scan2,
            category=self.category,
            brand=None,
            title="No Brand Item",
            confidence=Decimal("0.50"),
            provider_name="mock",
        )
        self.assertIsNone(item.brand)

    def test_category_protect_on_delete(self):
        """Deleting a category that has items raises ProtectedError."""
        from django.db.models import ProtectedError

        IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            title="Protected Item",
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_brand_set_null_on_delete(self):
        """Deleting a brand sets identified_item.brand to NULL."""
        item = IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            brand=self.brand,
            title="Brand Delete Test",
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        self.brand.delete()
        item.refresh_from_db()
        self.assertIsNone(item.brand)

    def test_one_to_one_scan(self):
        """Each scan can have at most one IdentifiedItem."""
        IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            title="First",
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IdentifiedItem.objects.create(
                    scan=self.scan,
                    category=self.category,
                    title="Second",
                    confidence=Decimal("0.80"),
                    provider_name="mock",
                )

    def test_jsonb_attributes(self):
        """JSONB attributes field stores and retrieves complex data."""
        attrs = {
            "color": "red",
            "size": "L",
            "materials": ["cotton", "polyester"],
            "measurements": {"chest": 42, "length": 28},
        }
        item = IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            title="JSONB Test",
            attributes=attrs,
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        item.refresh_from_db()
        self.assertEqual(item.attributes["color"], "red")
        self.assertEqual(item.attributes["materials"], ["cotton", "polyester"])
        self.assertEqual(item.attributes["measurements"]["chest"], 42)

    def test_str_with_brand(self):
        item = IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            brand=self.brand,
            title="Nice Shoes",
            condition=IdentifiedItem.Condition.GOOD,
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        s = str(item)
        self.assertIn("Test Brand", s)
        self.assertIn("Nice Shoes", s)
        self.assertIn("Good", s)


# ═══════════════════════════════════════════════════════════════════════
# PriceEstimate tests
# ═══════════════════════════════════════════════════════════════════════


class TestPriceEstimateModel(TestCase):
    """Tests for the PriceEstimate model."""

    def setUp(self):
        self.category = Category.objects.create(name="Price Cat")
        self.scan = Scan.objects.create(
            session_key="price-test",
            status=Scan.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.item = IdentifiedItem.objects.create(
            scan=self.scan,
            category=self.category,
            title="Price Test Item",
            confidence=Decimal("0.90"),
            provider_name="mock",
        )

    def test_create_price_estimate(self):
        est = PriceEstimate.objects.create(
            identified_item=self.item,
            currency="USD",
            price_min=Decimal("80.00"),
            price_typical=Decimal("100.00"),
            price_max=Decimal("120.00"),
            source_type=PriceEstimate.SourceType.MARKET_DATA,
            source_name="test",
            sample_size=15,
            methodology_version="v1",
        )
        self.assertEqual(est.price_typical, Decimal("100.00"))
        self.assertEqual(est.source_type, "market_data")

    def test_check_min_lte_typical(self):
        """price_min must be <= price_typical."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PriceEstimate.objects.create(
                    identified_item=self.item,
                    currency="USD",
                    price_min=Decimal("150.00"),
                    price_typical=Decimal("100.00"),
                    price_max=Decimal("200.00"),
                    source_type=PriceEstimate.SourceType.MANUAL,
                )

    def test_check_typical_lte_max(self):
        """price_typical must be <= price_max."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PriceEstimate.objects.create(
                    identified_item=self.item,
                    currency="USD",
                    price_min=Decimal("50.00"),
                    price_typical=Decimal("200.00"),
                    price_max=Decimal("100.00"),
                    source_type=PriceEstimate.SourceType.MANUAL,
                )

    def test_check_min_non_negative(self):
        """price_min must be >= 0."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PriceEstimate.objects.create(
                    identified_item=self.item,
                    currency="USD",
                    price_min=Decimal("-1.00"),
                    price_typical=Decimal("50.00"),
                    price_max=Decimal("100.00"),
                    source_type=PriceEstimate.SourceType.MANUAL,
                )

    def test_equal_min_typical_max(self):
        """min == typical == max is valid (exact price)."""
        est = PriceEstimate.objects.create(
            identified_item=self.item,
            currency="USD",
            price_min=Decimal("100.00"),
            price_typical=Decimal("100.00"),
            price_max=Decimal("100.00"),
            source_type=PriceEstimate.SourceType.MANUAL,
        )
        self.assertEqual(est.price_min, est.price_typical)

    def test_multiple_estimates_per_item(self):
        """An item can have multiple estimates (re-evaluation)."""
        PriceEstimate.objects.create(
            identified_item=self.item,
            currency="USD",
            price_min=Decimal("80.00"),
            price_typical=Decimal("100.00"),
            price_max=Decimal("120.00"),
            source_type=PriceEstimate.SourceType.MARKET_DATA,
        )
        PriceEstimate.objects.create(
            identified_item=self.item,
            currency="USD",
            price_min=Decimal("85.00"),
            price_typical=Decimal("105.00"),
            price_max=Decimal("125.00"),
            source_type=PriceEstimate.SourceType.MARKET_DATA,
            methodology_version="v2",
        )
        self.assertEqual(
            PriceEstimate.objects.filter(identified_item=self.item).count(), 2
        )

    def test_cascade_on_item_delete(self):
        """Deleting the identified item cascades to estimates."""
        PriceEstimate.objects.create(
            identified_item=self.item,
            currency="USD",
            price_min=Decimal("80.00"),
            price_typical=Decimal("100.00"),
            price_max=Decimal("120.00"),
            source_type=PriceEstimate.SourceType.MARKET_DATA,
        )
        self.item.delete()
        self.assertEqual(PriceEstimate.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════
# MarketPriceObservation tests
# ═══════════════════════════════════════════════════════════════════════


class TestMarketPriceObservationModel(TestCase):
    """Tests for the MarketPriceObservation model."""

    def test_create_observation(self):
        obs = MarketPriceObservation.objects.create(
            product_key="test-brand/test-model",
            source="test-marketplace",
            observed_price=Decimal("99.99"),
            currency="USD",
            observation_type=MarketPriceObservation.ObservationType.SOLD,
            observed_on=date.today(),
        )
        self.assertEqual(obs.observed_price, Decimal("99.99"))
        self.assertEqual(obs.observation_type, "sold")

    def test_price_must_be_positive(self):
        """observed_price must be > 0."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPriceObservation.objects.create(
                    product_key="test/zero",
                    source="test",
                    observed_price=Decimal("0.00"),
                    currency="USD",
                    observation_type=MarketPriceObservation.ObservationType.ASKING,
                    observed_on=date.today(),
                )

    def test_negative_price_rejected(self):
        """Negative prices are rejected by the CHECK constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPriceObservation.objects.create(
                    product_key="test/neg",
                    source="test",
                    observed_price=Decimal("-10.00"),
                    currency="USD",
                    observation_type=MarketPriceObservation.ObservationType.SOLD,
                    observed_on=date.today(),
                )

    def test_identified_item_set_null_on_delete(self):
        """Deleting the linked item sets observation.identified_item to NULL."""
        cat = Category.objects.create(name="Obs Cat")
        scan = Scan.objects.create(session_key="obs-test")
        item = IdentifiedItem.objects.create(
            scan=scan,
            category=cat,
            title="Obs Item",
            confidence=Decimal("0.90"),
            provider_name="mock",
        )
        obs = MarketPriceObservation.objects.create(
            product_key="obs/test",
            identified_item=item,
            source="test",
            observed_price=Decimal("50.00"),
            currency="USD",
            observation_type=MarketPriceObservation.ObservationType.SOLD,
            observed_on=date.today(),
        )
        item.delete()
        obs.refresh_from_db()
        self.assertIsNone(obs.identified_item)

    def test_asking_vs_sold_types(self):
        """Both observation types can be created."""
        for obs_type in [
            MarketPriceObservation.ObservationType.ASKING,
            MarketPriceObservation.ObservationType.SOLD,
        ]:
            obs = MarketPriceObservation.objects.create(
                product_key="type/test",
                source="test",
                observed_price=Decimal("75.00"),
                currency="USD",
                observation_type=obs_type,
                observed_on=date.today(),
            )
            self.assertEqual(obs.observation_type, obs_type)

    def test_str_format(self):
        obs = MarketPriceObservation.objects.create(
            product_key="brand/model-x",
            source="test",
            observed_price=Decimal("123.45"),
            currency="USD",
            observation_type=MarketPriceObservation.ObservationType.SOLD,
            observed_on=date(2024, 6, 15),
        )
        s = str(obs)
        self.assertIn("brand/model-x", s)
        self.assertIn("123.45", s)
        self.assertIn("Sold", s)


# ═══════════════════════════════════════════════════════════════════════
# Seed data verification
# ═══════════════════════════════════════════════════════════════════════


class TestSeedDataIntegrity(TestCase):
    """
    Verify that the seed_demo_data command produces valid, consistent data.
    We re-run the seed in a test transaction so it doesn't pollute other tests.
    """

    def setUp(self):
        from django.core.management import call_command
        call_command("seed_demo_data", "--flush", verbosity=0)

    def test_categories_created(self):
        self.assertEqual(Category.objects.count(), 8)

    def test_brands_created(self):
        self.assertEqual(Brand.objects.filter(name__startswith="DEMO-").count(), 8)

    def test_items_created(self):
        self.assertEqual(
            IdentifiedItem.objects.filter(provider_name="mock_seed").count(), 12
        )

    def test_observations_created(self):
        obs_count = MarketPriceObservation.objects.filter(
            source__startswith="DEMO"
        ).count()
        self.assertGreaterEqual(obs_count, 12 * 15)  # At least 15 per item
        self.assertLessEqual(obs_count, 12 * 30)  # At most 30 per item

    def test_estimates_created(self):
        self.assertEqual(
            PriceEstimate.objects.filter(source_name__startswith="DEMO").count(), 12
        )

    def test_estimate_constraints_hold(self):
        """All seed estimates satisfy min <= typical <= max."""
        for est in PriceEstimate.objects.filter(source_name__startswith="DEMO"):
            self.assertLessEqual(est.price_min, est.price_typical)
            self.assertLessEqual(est.price_typical, est.price_max)
            self.assertGreaterEqual(est.price_min, 0)

    def test_observation_prices_positive(self):
        """All seed observations have positive prices."""
        for obs in MarketPriceObservation.objects.filter(source__startswith="DEMO"):
            self.assertGreater(obs.observed_price, 0)

    def test_all_items_have_scans(self):
        """Every identified item links to a valid scan."""
        for item in IdentifiedItem.objects.filter(provider_name="mock_seed"):
            self.assertIsNotNone(item.scan)
            self.assertEqual(item.scan.status, Scan.Status.COMPLETED)

    def test_flush_and_reseed_is_idempotent(self):
        """Running --flush and re-seeding produces the same counts."""
        from django.core.management import call_command
        call_command("seed_demo_data", "--flush", verbosity=0)
        self.assertEqual(Category.objects.count(), 8)
        self.assertEqual(Brand.objects.filter(name__startswith="DEMO-").count(), 8)
