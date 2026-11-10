"""
Custom User model for ValuLens.

Uses email as the login identifier (no username field).
Must be defined BEFORE the first migration is run.
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager for the User model (email-based login)."""

    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user with the given email and password."""
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser with the given email and password."""
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for ValuLens.

    - Uses email as the unique identifier for authentication.
    - UUID public_id for user-facing references (prevents enumeration).
    - Standard integer PK for internal FK joins.
    """

    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Public-facing identifier. Never expose the integer PK.",
    )
    email = models.EmailField(
        max_length=254,
        unique=True,
        help_text="Email address used for login.",
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this user should be treated as active.",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Designates whether the user can log into the admin site.",
    )
    date_joined = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # Email is already required by USERNAME_FIELD

    class Meta:
        db_table = "accounts_user"
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    def get_full_name(self):
        """Return the first_name plus the last_name, with a space in between."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name or self.email.split("@")[0]


class AuditEvent(models.Model):
    """
    Immutable audit log for security-relevant actions.

    Never log passwords, tokens, or unnecessary personal data in metadata.
    """

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        help_text="User who performed the action. Null for system actions or deleted users.",
    )
    action = models.CharField(
        max_length=50,
        help_text='Dotted action identifier, e.g., "scan.created", "sale.recorded".',
    )
    target_type = models.CharField(
        max_length=50,
        help_text='Model name of the target, e.g., "Scan", "Sale".',
    )
    target_id = models.CharField(
        max_length=50,
        help_text="PK or public_id of the target object.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sanitized context. NEVER include passwords, tokens, or PII.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "accounts_audit_event"
        verbose_name = "audit event"
        verbose_name_plural = "audit events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self):
        actor_str = self.actor.email if self.actor else "system"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_str}: {self.action} on {self.target_type}#{self.target_id}"
