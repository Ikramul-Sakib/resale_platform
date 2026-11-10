"""
Phase 4 tests — Frontend Auth, Registration, Dashboard, and Guest Scan Claiming.

Tests cover:
- Registration flow & validation (email uniqueness, password rules)
- Login flow & authentication checks (valid, invalid, inactive)
- Logout flow
- Guest scan claiming on login/registration
- AuditEvent creation on security actions
- Protected dashboard & profile views
"""

import uuid
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import AuditEvent
from apps.scans.models import Scan

User = get_user_model()


class TestRegistrationViews(TestCase):
    """Test user registration views and validation."""

    def setUp(self):
        self.client = Client()
        self.register_url = reverse("accounts:register")
        self.login_url = reverse("accounts:login")
        self.dashboard_url = reverse("accounts:dashboard")

    def test_register_page_renders_get(self):
        """GET /accounts/register/ renders successfully."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertContains(response, "Create Your Account")

    def test_signup_alias_works(self):
        """GET /accounts/signup/ also works as an alias."""
        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 200)

    def test_register_success(self):
        """Valid registration creates user, logs them in, and records AuditEvent."""
        payload = {
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
            "password": "StrongPassword987!",
            "password_confirm": "StrongPassword987!",
        }
        response = self.client.post(self.register_url, payload, follow=True)

        self.assertRedirects(response, self.dashboard_url)
        user = User.objects.filter(email="alice@example.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Smith")
        self.assertTrue(user.check_password("StrongPassword987!"))

        # User is logged in
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

        # AuditEvent is recorded
        event = AuditEvent.objects.filter(actor=user, action="user.registered").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.target_type, "User")
        self.assertEqual(event.target_id, str(user.pk))

    def test_register_duplicate_email_fails(self):
        """Registering with an already used email fails gracefully."""
        User.objects.create_user(email="alice@example.com", password="Password123!")

        payload = {
            "email": "alice@example.com",
            "password": "NewPassword456!",
            "password_confirm": "NewPassword456!",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "email", "An account with this email address already exists.")

    def test_register_password_mismatch(self):
        """Mismatched passwords return a validation error."""
        payload = {
            "email": "bob@example.com",
            "password": "PasswordOne123!",
            "password_confirm": "PasswordTwo456!",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "password_confirm", "Passwords do not match.")

    def test_register_too_short_password(self):
        """Password shorter than 8 chars is rejected by validators."""
        payload = {
            "email": "short@example.com",
            "password": "abc",
            "password_confirm": "abc",
        }
        response = self.client.post(self.register_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["password"])

    def test_authenticated_user_redirected_away_from_register(self):
        """Logged-in users are redirected away from registration page."""
        user = User.objects.create_user(email="logged@example.com", password="PassWord123!")
        self.client.force_login(user)

        response = self.client.get(self.register_url)
        self.assertRedirects(response, self.dashboard_url)


class TestLoginAndLogoutViews(TestCase):
    """Test user login and logout views."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse("accounts:login")
        self.logout_url = reverse("accounts:logout")
        self.dashboard_url = reverse("accounts:dashboard")
        self.user = User.objects.create_user(
            email="member@valulens.dev",
            password="MemberPass123!",
            first_name="Member",
        )

    def test_login_page_renders_get(self):
        """GET /accounts/login/ renders successfully."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, "Welcome Back")

    def test_login_success(self):
        """Valid email and password logs in and records AuditEvent."""
        response = self.client.post(
            self.login_url,
            {"email": "member@valulens.dev", "password": "MemberPass123!"},
            follow=True,
        )
        self.assertRedirects(response, self.dashboard_url)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

        event = AuditEvent.objects.filter(actor=self.user, action="user.login").first()
        self.assertIsNotNone(event)

    def test_login_with_next_param(self):
        """Login redirects to the next param if internal."""
        profile_url = reverse("accounts:profile")
        response = self.client.post(
            f"{self.login_url}?next={profile_url}",
            {"email": "member@valulens.dev", "password": "MemberPass123!"},
            follow=True,
        )
        self.assertRedirects(response, profile_url)

    def test_login_invalid_password(self):
        """Wrong password fails authentication with error message."""
        response = self.client.post(
            self.login_url,
            {"email": "member@valulens.dev", "password": "WrongPassword!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_inactive_user(self):
        """Inactive user cannot log in."""
        self.user.is_active = False
        self.user.save()

        response = self.client.post(
            self.login_url,
            {"email": "member@valulens.dev", "password": "MemberPass123!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout(self):
        """Logging out clears session and records AuditEvent."""
        self.client.force_login(self.user)
        response = self.client.get(self.logout_url, follow=True)
        self.assertRedirects(response, "/")
        self.assertNotIn("_auth_user_id", self.client.session)

        event = AuditEvent.objects.filter(actor=self.user, action="user.logout").first()
        self.assertIsNotNone(event)


class TestGuestScanClaiming(TestCase):
    """Test that guest scans are claimed when user logs in or registers."""

    def setUp(self):
        self.client = Client()

    def test_guest_scans_claimed_on_register(self):
        """Anonymous guest scans with session_key are claimed on user registration."""
        # Establish session
        session = self.client.session
        session["has_visited"] = True
        session.save()
        session_key = session.session_key

        # Create guest scan
        guest_scan = Scan.objects.create(session_key=session_key, status=Scan.Status.PENDING)

        # Register user in this session
        self.client.post(
            reverse("accounts:register"),
            {
                "email": "scanner@valulens.dev",
                "password": "ScannerPass123!",
                "password_confirm": "ScannerPass123!",
            },
        )

        guest_scan.refresh_from_db()
        user = User.objects.get(email="scanner@valulens.dev")
        self.assertEqual(guest_scan.user, user)
        self.assertEqual(guest_scan.session_key, "")

        # Verify claiming audit event
        claim_event = AuditEvent.objects.filter(actor=user, action="scans.claimed").first()
        self.assertIsNotNone(claim_event)
        self.assertEqual(claim_event.metadata.get("claimed_count"), 1)

    def test_guest_scans_claimed_on_login(self):
        """Anonymous guest scans are claimed when user logs in."""
        user = User.objects.create_user(email="existing@valulens.dev", password="Password123!")

        session = self.client.session
        session["active"] = True
        session.save()
        session_key = session.session_key

        scan1 = Scan.objects.create(session_key=session_key, status=Scan.Status.COMPLETED)
        scan2 = Scan.objects.create(session_key=session_key, status=Scan.Status.PENDING)

        self.client.post(
            reverse("accounts:login"),
            {"email": "existing@valulens.dev", "password": "Password123!"},
        )

        scan1.refresh_from_db()
        scan2.refresh_from_db()
        self.assertEqual(scan1.user, user)
        self.assertEqual(scan1.session_key, "")
        self.assertEqual(scan2.user, user)
        self.assertEqual(scan2.session_key, "")


class TestDashboardAndProfileViews(TestCase):
    """Test dashboard protection and profile update functionality."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="dashboard@valulens.dev",
            password="PassWord123!",
            first_name="Dash",
            last_name="Board",
        )
        self.dashboard_url = reverse("accounts:dashboard")
        self.profile_url = reverse("accounts:profile")

    def test_dashboard_requires_login(self):
        """Unauthenticated access redirects to login."""
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, f"/accounts/login/?next={self.dashboard_url}")

    def test_dashboard_authenticated(self):
        """Authenticated access renders dashboard with user info."""
        self.client.force_login(self.user)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/dashboard.html")
        self.assertContains(response, "Hello, Dash")
        self.assertContains(response, str(self.user.public_id))

    def test_profile_update(self):
        """User can update first and last name via profile form."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.profile_url,
            {"first_name": "UpdatedFirst", "last_name": "UpdatedLast"},
            follow=True,
        )
        self.assertRedirects(response, self.profile_url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "UpdatedFirst")
        self.assertEqual(self.user.last_name, "UpdatedLast")

        # Verify audit event
        event = AuditEvent.objects.filter(actor=self.user, action="user.profile_updated").first()
        self.assertIsNotNone(event)
