import typing

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Province(models.Model):
    """Standardized Philippine provinces."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "user_provinces"
        verbose_name = "Province"
        verbose_name_plural = "Provinces"

    def __str__(self) -> str:
        return self.name


class Municipality(models.Model):
    """Standardized cities/municipalities in the Philippines."""

    name = models.CharField(max_length=100)
    province = models.ForeignKey(
        Province,
        on_delete=models.CASCADE,
        related_name="municipalities",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "user_municipalities"
        verbose_name = "Municipality"
        verbose_name_plural = "Municipalities"

    def __str__(self) -> str:
        return f"{self.name}, {self.province.name}" if self.province else self.name


class UserManager(BaseUserManager):
    """Custom manager for User with email as the unique identifier."""

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)

        # Auto-assign if affiliation was not passed
        if "affiliation" not in extra_fields:
            if "iskolar" in email.lower():
                extra_fields["affiliation"] = self.model.AffiliationChoices.STUDENT
            elif "pup.edu.ph" in email.lower():
                extra_fields["affiliation"] = self.model.AffiliationChoices.FACULTY

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        # Administrator authority is carried by is_staff, not by affiliation.
        # Affiliation only records the user's relationship to PUP (FR1).
        extra_fields.setdefault("affiliation", User.AffiliationChoices.FACULTY)
        extra_fields.setdefault("account_status", User.AccountStatusChoices.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom user model for BRB platform (FR1, FR2, FR4, FR5, FR13).
    Restricted to PUP webmail addresses (@iskolarngbayan.pup.edu.ph, @pup.edu.ph).

    `affiliation` records only the user's relationship to PUP. Platform
    authority (including Administrator access to identity documents, FR3) is
    carried by Django's `is_staff` flag, never by `affiliation`.
    """

    class AffiliationChoices(models.TextChoices):
        STUDENT = "Student", "Student"
        FACULTY = "Faculty", "Faculty"
        STAFF = "Staff", "Staff"

    class AccountStatusChoices(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        PENDING_REVIEW = "pending_review", "Pending Review"
        BANNED = "banned", "Banned"
        DEACTIVATED = "deactivated", "Deactivated"

    class LenderStatusChoices(models.TextChoices):
        NONE = "none", "None"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=20)
    affiliation = models.CharField(
        max_length=20,
        choices=AffiliationChoices.choices,
        default=AffiliationChoices.STUDENT,
    )
    bio = models.TextField(blank=True, null=True)
    photo = models.ImageField(upload_to="profile_photos/", blank=True, null=True)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    account_status = models.CharField(
        max_length=20,
        choices=AccountStatusChoices.choices,
        default=AccountStatusChoices.ACTIVE,
    )
    lender_status = models.CharField(
        max_length=20,
        choices=LenderStatusChoices.choices,
        default=LenderStatusChoices.NONE,
    )
    street_address = models.CharField(max_length=255, blank=True, default="")
    municipality = models.ForeignKey(
        Municipality,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    province = models.ForeignKey(
        Province,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: typing.ClassVar[list[str]] = [
        "full_name",
        "contact_number",
        "affiliation",
    ]

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return f"{self.full_name} ({self.email})"


class IdentityDocumentType(models.Model):
    """Document type lookup table (draw.io: identidy_documents_types)."""

    name = models.CharField(max_length=50, unique=True)  # pup_id, government_id

    class Meta:
        db_table = "identity_document_types"
        verbose_name = "Identity Document Type"
        verbose_name_plural = "Identity Document Types"

    def __str__(self) -> str:
        return self.name


class IdentityDocumentStatus(models.Model):
    """Verification status lookup table (draw.io: identidy_documents_statuses)."""

    name = models.CharField(max_length=50, unique=True)  # pending, approved, rejected

    class Meta:
        db_table = "identity_document_statuses"
        verbose_name = "Identity Document Status"
        verbose_name_plural = "Identity Document Statuses"

    def __str__(self) -> str:
        return self.name


class IdentityDocument(models.Model):
    """
    Supporting identification document for identity verification (FR3).
    Strictly confidential: accessible exclusively to administrators.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="identity_documents",
    )
    document_type = models.ForeignKey(
        IdentityDocumentType,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    id_number = models.CharField(max_length=100)
    file_reference = models.FileField(
        upload_to="identity_documents/"
    )  # Encrypted storage reference
    status = models.ForeignKey(
        IdentityDocumentStatus,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    rejection_reason = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_identity_documents",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity_documents"
        verbose_name = "Identity Document"
        verbose_name_plural = "Identity Documents"

    def __str__(self) -> str:
        return f"{self.user.email} - {self.document_type.name} ({self.id_number})"
