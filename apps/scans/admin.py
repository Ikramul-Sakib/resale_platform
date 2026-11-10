"""Admin configuration for scan models."""

from django.contrib import admin

from .models import IdentifiedItem, Scan, ScanImage


class ScanImageInline(admin.TabularInline):
    model = ScanImage
    extra = 0
    readonly_fields = ("storage_key", "content_type", "file_size", "sha256", "created_at")


class IdentifiedItemInline(admin.StackedInline):
    model = IdentifiedItem
    extra = 0
    readonly_fields = ("provider_name", "confidence", "created_at")


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ("public_id", "user", "status", "created_at", "completed_at")
    list_filter = ("status", "created_at")
    search_fields = ("public_id", "user__email", "session_key")
    readonly_fields = ("public_id", "created_at", "completed_at")
    raw_id_fields = ("user",)
    inlines = [ScanImageInline, IdentifiedItemInline]
    ordering = ("-created_at",)


@admin.register(ScanImage)
class ScanImageAdmin(admin.ModelAdmin):
    list_display = ("pk", "scan", "content_type", "file_size", "created_at")
    list_filter = ("content_type",)
    search_fields = ("scan__public_id", "storage_key")
    readonly_fields = ("created_at",)
    raw_id_fields = ("scan",)


@admin.register(IdentifiedItem)
class IdentifiedItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "brand",
        "condition",
        "confidence",
        "provider_name",
        "is_user_corrected",
        "created_at",
    )
    list_filter = ("category", "condition", "provider_name", "is_user_corrected")
    search_fields = ("title", "model_name", "brand__name")
    readonly_fields = ("created_at",)
    raw_id_fields = ("scan", "category", "brand")
