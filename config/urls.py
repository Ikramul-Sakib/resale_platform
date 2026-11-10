"""
ValuLens URL Configuration.

Top-level URL dispatcher. Each app registers its own URL patterns.
"""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    # Home
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),

    # Admin
    path("admin/", admin.site.urls),

    # App URLs (to be added in subsequent phases)
    path("accounts/", include("apps.accounts.urls")),

    # API (to be added in Phase 10)
    # path("api/v1/", include("config.api_urls")),
]
