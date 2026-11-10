"""
Management command: seed_demo_data

Populates the database with DEMO/PLACEHOLDER data for local development.
All data is clearly labelled as demo data — nothing here represents
real market prices or real products.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --flush   # Wipe and re-seed
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Brand, Category
from apps.pricing.models import MarketPriceObservation, PriceEstimate
from apps.scans.models import IdentifiedItem, Scan, ScanImage


# ─────────────────────────────────────────────────────────────────────
# DEMO DATA — clearly labelled. None of this is real market data.
# ─────────────────────────────────────────────────────────────────────

DEMO_CATEGORIES = [
    {"name": "Sneakers", "description": "DEMO: Athletic and casual footwear."},
    {"name": "Handbags", "description": "DEMO: Purses, totes, and designer bags."},
    {"name": "Watches", "description": "DEMO: Wristwatches and timepieces."},
    {"name": "Electronics", "description": "DEMO: Phones, tablets, and gadgets."},
    {"name": "Streetwear", "description": "DEMO: T-shirts, hoodies, and limited drops."},
    {"name": "Vintage Clothing", "description": "DEMO: Pre-2000s apparel and accessories."},
    {"name": "Trading Cards", "description": "DEMO: Sports and collectible cards."},
    {"name": "Toys & Collectibles", "description": "DEMO: Action figures, LEGO, and vinyl."},
]

DEMO_BRANDS = [
    {"name": "DEMO-Nike", "description": "DEMO: Placeholder athletic brand."},
    {"name": "DEMO-Adidas", "description": "DEMO: Placeholder athletic brand."},
    {"name": "DEMO-LuxBag Co", "description": "DEMO: Placeholder luxury handbag brand."},
    {"name": "DEMO-ChronoTime", "description": "DEMO: Placeholder watch brand."},
    {"name": "DEMO-TechGadget", "description": "DEMO: Placeholder electronics brand."},
    {"name": "DEMO-StreetLabel", "description": "DEMO: Placeholder streetwear brand."},
    {"name": "DEMO-RetroWear", "description": "DEMO: Placeholder vintage brand."},
    {"name": "DEMO-CardVault", "description": "DEMO: Placeholder trading cards brand."},
]

# (category_index, brand_index, title, model_name, condition, attributes, base_price)
DEMO_ITEMS = [
    (0, 0, "DEMO: Air Runner 2024", "AR-2024-WHT", "excellent", {"color": "White", "size": "10"}, Decimal("120.00")),
    (0, 0, "DEMO: Retro Dunk Low", "RDL-BLK-RED", "very_good", {"color": "Black/Red", "size": "9.5"}, Decimal("95.00")),
    (0, 1, "DEMO: Ultraboost Lite", "UBL-GRY-2023", "new_with_tags", {"color": "Grey", "size": "11"}, Decimal("150.00")),
    (1, 2, "DEMO: Classic Tote Bag", "CTB-TAN-M", "good", {"color": "Tan", "size": "Medium"}, Decimal("350.00")),
    (1, 2, "DEMO: Mini Crossbody", "MCB-BLK-S", "excellent", {"color": "Black", "size": "Small"}, Decimal("275.00")),
    (2, 3, "DEMO: Chrono Pilot 42mm", "CP-42-SS", "very_good", {"material": "Stainless Steel", "diameter": "42mm"}, Decimal("800.00")),
    (3, 4, "DEMO: SmartPhone Pro 15", "SP15-128-BLK", "good", {"storage": "128GB", "color": "Black"}, Decimal("450.00")),
    (3, 4, "DEMO: Tablet Air 11", "TA11-256-SLV", "excellent", {"storage": "256GB", "color": "Silver"}, Decimal("380.00")),
    (4, 5, "DEMO: Box Logo Hoodie", "BLH-RED-L", "new_without_tags", {"color": "Red", "size": "L"}, Decimal("220.00")),
    (5, 6, "DEMO: 90s Band Tee", "90BT-VTG-XL", "fair", {"era": "1990s", "size": "XL"}, Decimal("65.00")),
    (6, 7, "DEMO: Rookie Card Pack", "RCP-2023-S1", "new_with_tags", {"year": "2023", "series": "Series 1"}, Decimal("45.00")),
    (7, None, "DEMO: Vintage Action Figure", "VAF-1985-MIB", "good", {"year": "1985", "packaging": "Mint in Box"}, Decimal("180.00")),
]


class Command(BaseCommand):
    help = "Seed the database with DEMO/PLACEHOLDER data for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing demo data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            self.stdout.write("Flushing existing demo data...")
            MarketPriceObservation.objects.filter(source__startswith="DEMO").delete()
            PriceEstimate.objects.filter(source_name__startswith="DEMO").delete()
            IdentifiedItem.objects.filter(provider_name="mock_seed").delete()
            ScanImage.objects.filter(storage_key__startswith="demo/").delete()
            Scan.objects.filter(session_key="demo-seed-session").delete()
            Brand.objects.filter(name__startswith="DEMO-").delete()
            Category.objects.filter(description__startswith="DEMO").delete()
            self.stdout.write(self.style.SUCCESS("  Flushed."))

        # --- Categories ---
        categories = []
        for data in DEMO_CATEGORIES:
            cat, created = Category.objects.get_or_create(
                name=data["name"],
                defaults={"description": data["description"]},
            )
            categories.append(cat)
            status = "Created" if created else "Exists"
            self.stdout.write(f"  Category: {cat.name} [{status}]")

        # --- Brands ---
        brands = []
        for data in DEMO_BRANDS:
            brand, created = Brand.objects.get_or_create(
                name=data["name"],
                defaults={"description": data["description"]},
            )
            brands.append(brand)
            status = "Created" if created else "Exists"
            self.stdout.write(f"  Brand: {brand.name} [{status}]")

        # --- Scans + IdentifiedItems + ScanImages ---
        items_created = []
        for cat_idx, brand_idx, title, model_name, condition, attrs, base_price in DEMO_ITEMS:
            # Create scan
            scan = Scan.objects.create(
                user=None,
                session_key="demo-seed-session",
                status=Scan.Status.COMPLETED,
                completed_at=timezone.now(),
            )

            # Create placeholder scan image
            ScanImage.objects.create(
                scan=scan,
                storage_key=f"demo/{scan.public_id}.jpg",
                content_type="image/jpeg",
                file_size=102400,  # 100KB placeholder
                sha256="0" * 64,  # Placeholder hash
            )

            # Create identified item
            brand = brands[brand_idx] if brand_idx is not None else None
            item = IdentifiedItem.objects.create(
                scan=scan,
                category=categories[cat_idx],
                brand=brand,
                title=title,
                model_name=model_name,
                condition=condition,
                attributes=attrs,
                confidence=Decimal("0.85"),
                provider_name="mock_seed",
                is_user_corrected=False,
            )
            items_created.append((item, base_price))
            self.stdout.write(f"  Item: {title}")

        # --- MarketPriceObservations ---
        self.stdout.write("\n  Creating DEMO market observations...")
        today = date.today()
        observations_bulk = []

        for item, base_price in items_created:
            product_key = f"{item.brand.slug if item.brand else 'unknown'}/{item.model_name}".lower()

            # Generate 15–30 observations over the last 90 days
            num_obs = random.randint(15, 30)
            for i in range(num_obs):
                days_ago = random.randint(0, 90)
                obs_date = today - timedelta(days=days_ago)

                # Random price variation: ±25% around base_price
                variation = Decimal(str(random.uniform(0.75, 1.25)))
                price = (base_price * variation).quantize(Decimal("0.01"))

                # 60% sold, 40% asking
                obs_type = (
                    MarketPriceObservation.ObservationType.SOLD
                    if random.random() < 0.6
                    else MarketPriceObservation.ObservationType.ASKING
                )

                observations_bulk.append(
                    MarketPriceObservation(
                        product_key=product_key,
                        identified_item=item,
                        source=f"DEMO-marketplace-{random.choice(['alpha', 'beta', 'gamma'])}",
                        observed_price=price,
                        currency="USD",
                        observation_type=obs_type,
                        observed_on=obs_date,
                    )
                )

        MarketPriceObservation.objects.bulk_create(observations_bulk)
        self.stdout.write(f"  Created {len(observations_bulk)} DEMO observations.")

        # --- PriceEstimates ---
        self.stdout.write("\n  Creating DEMO price estimates...")
        for item, base_price in items_created:
            price_min = (base_price * Decimal("0.80")).quantize(Decimal("0.01"))
            price_max = (base_price * Decimal("1.20")).quantize(Decimal("0.01"))

            PriceEstimate.objects.create(
                identified_item=item,
                currency="USD",
                price_min=price_min,
                price_typical=base_price,
                price_max=price_max,
                source_type=PriceEstimate.SourceType.MARKET_DATA,
                source_name="DEMO-valulens-seed",
                sample_size=random.randint(10, 25),
                confidence=Decimal("0.75"),
                uncertainty=(base_price * Decimal("0.10")).quantize(Decimal("0.01")),
                methodology_version="v1",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Seed complete: "
                f"{len(DEMO_CATEGORIES)} categories, "
                f"{len(DEMO_BRANDS)} brands, "
                f"{len(DEMO_ITEMS)} items, "
                f"{len(observations_bulk)} observations, "
                f"{len(DEMO_ITEMS)} estimates."
            )
        )

