"""
Scan workflow views: upload, status/result, private image, correction, history.

Views stay thin; business logic lives in apps.scans.services and
apps.recognition.services. Every scan lookup is scoped to the requester
(user, or guest session) and returns 404 otherwise.
"""

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.recognition.exceptions import ImageValidationError
from apps.recognition.services import correct_identified_item

from . import services
from .forms import IdentificationCorrectionForm, ScanUploadForm
from .models import IdentifiedItem, Scan
from .throttling import scan_upload_rate_limited

RATE_LIMIT_MESSAGE = "Too many uploads from your network. Please wait a while and try again."


def scans_for_request(request):
    if request.user.is_authenticated:
        return Scan.objects.filter(user=request.user)
    session_key = request.session.session_key
    if session_key:
        return Scan.objects.filter(user__isnull=True, session_key=session_key)
    return Scan.objects.none()


def get_scan_or_404(request, public_id) -> Scan:
    scan = scans_for_request(request).filter(public_id=public_id).first()
    if scan is None:
        raise Http404("Scan not found.")
    return scan


@require_http_methods(["GET", "POST"])
def scan_upload_view(request):
    status = 200
    if request.method == "POST":
        form = ScanUploadForm(request.POST, request.FILES)
        if scan_upload_rate_limited(request):
            form.add_error(None, RATE_LIMIT_MESSAGE)
            status = 429
        elif form.is_valid():
            session_key = ""
            if not request.user.is_authenticated:
                if not request.session.session_key:
                    request.session.create()
                session_key = request.session.session_key
            try:
                scan = services.create_scan(
                    form.cleaned_data["image"], user=request.user, session_key=session_key
                )
            except ImageValidationError as exc:
                form.add_error("image", exc.user_message)
                status = 400
            except services.GuestScanLimitExceeded as exc:
                form.add_error(None, exc.user_message)
                status = 429
            else:
                return redirect("scans:detail", public_id=scan.public_id)
        else:
            status = 400
    else:
        form = ScanUploadForm()

    context = {
        "form": form,
        "max_upload_mb": settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024),
        "retention_hours": settings.GUEST_SCAN_RETENTION_HOURS,
    }
    return render(request, "scans/upload.html", context, status=status)


@require_GET
def scan_detail_view(request, public_id):
    scan = get_scan_or_404(request, public_id)
    item = IdentifiedItem.objects.select_related("category", "brand").filter(scan=scan).first()
    context = {
        "scan": scan,
        "item": item,
        "image": scan.images.order_by("created_at").first(),
        "in_progress": scan.status in (Scan.Status.PENDING, Scan.Status.PROCESSING),
        "retention_hours": settings.GUEST_SCAN_RETENTION_HOURS,
    }
    return render(request, "scans/detail.html", context)


@require_GET
def scan_image_view(request, public_id):
    scan = get_scan_or_404(request, public_id)
    image = scan.images.order_by("created_at").first()
    if image is None:
        raise Http404("Image not found.")
    try:
        fh = default_storage.open(image.storage_key, "rb")
    except FileNotFoundError as exc:
        raise Http404("Image not found.") from exc
    response = FileResponse(fh, content_type=image.content_type)
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = "inline"
    return response


@require_http_methods(["GET", "POST"])
def scan_correct_view(request, public_id):
    scan = get_scan_or_404(request, public_id)
    item = IdentifiedItem.objects.filter(scan=scan).first()
    if scan.status != Scan.Status.COMPLETED or item is None:
        raise Http404("No identification to correct.")

    if request.method == "POST":
        form = IdentificationCorrectionForm(request.POST, instance=item)
        if form.is_valid():
            correct_identified_item(item, form.cleaned_data, actor=request.user)
            messages.success(request, "Your correction was saved.")
            return redirect("scans:detail", public_id=scan.public_id)
    else:
        form = IdentificationCorrectionForm(instance=item)
    return render(request, "scans/correct.html", {"scan": scan, "item": item, "form": form})


@require_GET
def scan_history_view(request):
    scans = scans_for_request(request).select_related("identified_item").order_by("-created_at")
    page_obj = Paginator(scans, 10).get_page(request.GET.get("page"))
    context = {
        "page_obj": page_obj,
        "scans": page_obj.object_list,
        "retention_hours": settings.GUEST_SCAN_RETENTION_HOURS,
    }
    return render(request, "scans/history.html", context)
