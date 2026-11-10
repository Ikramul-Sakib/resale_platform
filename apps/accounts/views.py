"""
Authentication and account management views for ValuLens.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import LoginForm, ProfileUpdateForm, RegisterForm
from .services import claim_guest_scans, get_client_ip, record_audit_event


def register_view(request):
    """
    Handle user registration, auto-login, guest session scan claiming,
    and audit event creation.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # Remember the anonymous session key before login rotates the session ID
            guest_session_key = request.session.session_key

            user = form.save()

            # Log the user in
            login(request, user)

            # Claim any scans from the guest session
            if guest_session_key:
                claim_guest_scans(guest_session_key, user)

            # Record security audit event
            record_audit_event(
                action="user.registered",
                target_type="User",
                target_id=str(user.pk),
                actor=user,
                metadata={"ip": get_client_ip(request)},
            )

            messages.success(
                request,
                f"Welcome to ValuLens, {user.get_short_name()}! Your account has been created successfully.",
            )

            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def login_view(request):
    """
    Handle user authentication, session creation, guest scan claiming,
    and audit event logging.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            guest_session_key = request.session.session_key

            login(request, user)

            # Claim any scans performed as a guest in this session
            if guest_session_key:
                claimed = claim_guest_scans(guest_session_key, user)
                if claimed > 0:
                    messages.info(
                        request,
                        f"Linked {claimed} previous scan{'s' if claimed != 1 else ''} to your account.",
                    )

            # Record audit event
            record_audit_event(
                action="user.login",
                target_type="User",
                target_id=str(user.pk),
                actor=user,
                metadata={"ip": get_client_ip(request)},
            )

            messages.success(request, f"Welcome back, {user.get_short_name()}!")

            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = LoginForm(request)

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def logout_view(request):
    """
    Log out the authenticated user and record an audit event.
    Supports both POST and GET for clean navigation.
    """
    if request.user.is_authenticated:
        record_audit_event(
            action="user.logout",
            target_type="User",
            target_id=str(request.user.pk),
            actor=request.user,
            metadata={"ip": get_client_ip(request)},
        )
        logout(request)
        messages.info(request, "You have been signed out.")

    return redirect(settings.LOGOUT_REDIRECT_URL)


@login_required
def dashboard_view(request):
    """
    Authenticated user dashboard overview: profile summary, recent scans,
    and recent activity.
    """
    user = request.user
    recent_scans = user.scans.all().order_by("-created_at")[:8] if hasattr(user, "scans") else []
    recent_events = user.audit_events.all().order_by("-created_at")[:5]

    context = {
        "user": user,
        "recent_scans": recent_scans,
        "recent_events": recent_events,
        "scans_count": user.scans.count() if hasattr(user, "scans") else 0,
    }
    return render(request, "accounts/dashboard.html", context)


@login_required
def profile_view(request):
    """
    View and update user profile information.
    """
    user = request.user
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            record_audit_event(
                action="user.profile_updated",
                target_type="User",
                target_id=str(user.pk),
                actor=user,
                metadata={"ip": get_client_ip(request)},
            )
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileUpdateForm(instance=user)

    return render(request, "accounts/profile.html", {"form": form, "user": user})
