"""Admin configuration for pricing models."""

from django.contrib import admin

from .models import MarketPriceObservation, PriceEstimate


@admin.register(PriceEstimate)
class PriceEstimateAdmin(admin.ModelAdmin):
    list_display = (
        "identified_item",
        "currency",
        "price_min",
        "price_typical",
        "price_max",
        "source_type",
        "sample_size",
        "methodology_version",
        "created_at",
    )
    list_filter = ("source_type", "currency", "methodology_version")
    search_fields = ("identified_item__title",)
    readonly_fields = ("created_at",)
    raw_id_fields = ("identified_item",)


@admin.register(MarketPriceObservation)
class MarketPriceObservationAdmin(admin.ModelAdmin):
    list_display = (
        "product_key",
        "source",
        "observed_price",
        "currency",
        "observation_type",
        "observed_on",
        "collected_at",
    )
    list_filter = ("observation_type", "source", "currency")
    search_fields = ("product_key",)
    readonly_fields = ("collected_at",)
    raw_id_fields = ("identified_item",)
    date_hierarchy = "observed_on"
