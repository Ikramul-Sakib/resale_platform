"""
Scan workflow URL patterns. Scans are addressed by UUID public_id only.
"""

from django.urls import path

from . import views

app_name = "scans"

urlpatterns = [
    path("", views.scan_upload_view, name="upload"),
    path("history/", views.scan_history_view, name="history"),
    path("<uuid:public_id>/", views.scan_detail_view, name="detail"),
    path("<uuid:public_id>/image/", views.scan_image_view, name="image"),
    path("<uuid:public_id>/correct/", views.scan_correct_view, name="correct"),
]
