"""
Phase 2 scaffold verification tests.

Confirms that the project structure, custom User model, database
connection, and basic URL routing all work correctly against PostgreSQL.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, Client

User = get_user_model()


class TestCustomUserModel(TestCase):
    """Verify the custom User model with email-based authentication."""

    def test_create_user(self):
        """Regular user creation with email as identifier."""
        user = User.objects.create_user(
            email="test@valulens.dev",
            password="TestPass123!",
            first_name="Test",
            last_name="User",
        )
        self.assertEqual(user.email, "test@valulens.dev")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("TestPass123!"))
        self.assertIsInstance(user.public_id, uuid.UUID)
        self.assertEqual(str(user), "test@valulens.dev")

    def test_create_superuser(self):
        """Superuser creation with required flags."""
        admin = User.objects.create_superuser(
            email="admin@valulens.dev",
            password="AdminPass123!",
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_active)

    def test_email_required(self):
        """User creation without email raises ValueError."""
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="TestPass123!")

    def test_superuser_must_be_staff(self):
        """Superuser with is_staff=False raises ValueError."""
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="bad@valulens.dev",
                password="TestPass123!",
                is_staff=False,
            )

    def test_public_id_unique(self):
        """Each user gets a unique UUID public_id."""
        user1 = User.objects.create_user(email="u1@valulens.dev", password="Pass123!")
        user2 = User.objects.create_user(email="u2@valulens.dev", password="Pass123!")
        self.assertNotEqual(user1.public_id, user2.public_id)

    def test_get_full_name(self):
        """get_full_name returns first + last or email."""
        user = User.objects.create_user(email="name@valulens.dev", password="Pass123!")
        self.assertEqual(user.get_full_name(), "name@valulens.dev")
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        self.assertEqual(user.get_full_name(), "Jane Doe")

    def test_get_short_name(self):
        """get_short_name returns first_name or email prefix."""
        user = User.objects.create_user(email="hello@valulens.dev", password="Pass123!")
        self.assertEqual(user.get_short_name(), "hello")
        user.first_name = "Hi"
        user.save()
        self.assertEqual(user.get_short_name(), "Hi")


class TestAuditEvent(TestCase):
    """Verify the AuditEvent model."""

    def test_create_audit_event(self):
        """AuditEvent can be created with all fields."""
        from apps.accounts.models import AuditEvent

        user = User.objects.create_user(email="audit@valulens.dev", password="Pass123!")
        event = AuditEvent.objects.create(
            actor=user,
            action="test.action",
            target_type="User",
            target_id=str(user.pk),
            metadata={"detail": "test"},
        )
        self.assertEqual(event.action, "test.action")
        self.assertIn("audit@valulens.dev", str(event))

    def test_system_event_no_actor(self):
        """AuditEvent with no actor (system action)."""
        from apps.accounts.models import AuditEvent

        event = AuditEvent.objects.create(
            actor=None,
            action="system.startup",
            target_type="System",
            target_id="0",
        )
        self.assertIsNone(event.actor)
        self.assertIn("system", str(event))


class TestDatabaseConnection(TestCase):
    """Verify we are running against PostgreSQL, not SQLite."""

    def test_database_is_postgresql(self):
        """The test database must be PostgreSQL."""
        from django.db import connection
        self.assertEqual(connection.vendor, "postgresql")


class TestHomePageRoute(TestCase):
    """Verify the home page URL is routable."""

    def test_home_page_returns_200(self):
        """GET / should return 200."""
        client = Client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)

