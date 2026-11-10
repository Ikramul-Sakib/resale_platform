"""
Catalog models for ValuLens.

Category and Brand are shared reference data used across scans,
pricing, listings, and analytics. They use PROTECT on deletion
to prevent orphaning downstream records.
"""

from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    """
    Product category (e.g., Sneakers, Handbags, Electronics).

    Categories are shared reference data — deletion is blocked (PROTECT)
    if any IdentifiedItem, MarketplaceFeeRule, or ResaleIndexSnapshot
    references this category.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Display name of the category.",
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        help_text="URL-safe identifier. Auto-generated from name if blank.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional description of the category.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalog_category"
        verbose_name = "category"
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Brand(models.Model):
    """
    Product brand (e.g., Nike, Louis Vuitton, Apple).

    Brands are shared reference data — deletion uses SET_NULL on
    IdentifiedItem to allow items to exist without a brand.
    """

    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Display name of the brand.",
    )
    slug = models.SlugField(
        max_length=220,
        unique=True,
        help_text="URL-safe identifier. Auto-generated from name if blank.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional description of the brand.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalog_brand"
        verbose_name = "brand"
        verbose_name_plural = "brands"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
