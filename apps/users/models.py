import typing

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


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
    # CP-103 lockout state. Both columns are additive with a default/nullable so
    # the migration stays backward-compatible against a populated table: existing
    # rows simply start with a clean slate and no lock. See DECISIONS.md D-06 --
    # these two columns are the one place CP-103 needed to extend `users`.
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
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

    @property
    def is_email_verified(self) -> bool:
        """Whether CP-102's confirmation step has been completed."""
        return self.email_verified_at is not None

    @property
    def is_locked_out(self) -> bool:
        """
        Whether a CP-103 lockout is currently in force.

        A lockout that has run out is treated as absent here; the stale
        `locked_until` timestamp is cleared by the next successful login.
        """
        return self.locked_until is not None and self.locked_until > timezone.now()

    def has_verified_identity(self) -> bool:
        """
        Whether an Admin approved an identity document for this account (CP-105).

        This is the gate CP-105 puts in front of listing creation and borrow
        requests, and it is deliberately distinct from `is_email_verified`:
        confirming an email (CP-102) is not the same as having one's ID checked
        (CP-105/CP-106).
        """
        approved = IdentityDocumentStatus.objects.filter(name="approved").first()
        if approved is None:
            return False
        return self.identity_documents.filter(status=approved).exists()


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
    # CP-105: the document bytes live in Postgres, not on a filesystem or a third
    # party bucket. Render's filesystem is ephemeral and the free tier has no
    # persistent disk, so a FileField here would lose every upload on the next
    # redeploy. Keeping the blob in the row also makes "store the document and its
    # submission record" a single atomic write (DECISIONS.md D-13).
    document_data = models.BinaryField(editable=False)
    status = models.ForeignKey(
        IdentityDocumentStatus,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    # CP-105: the name printed on the uploaded document, kept so an Admin can
    # compare it against `users.full_name`. Set by the client at submission time;
    # CP-105 does no OCR, so this is the declared name, not a parsed one.
    name_on_document = models.CharField(max_length=255, blank=True, default="")
    # CP-105: raised automatically when name_on_document disagrees with the
    # registration name. The submission is still accepted -- a mismatch is a
    # reason for an Admin to look harder, not a reason to reject (CP-106).
    has_profile_mismatch = models.BooleanField(default=False)
    # CP-105: consent is a precondition of submission, so it is recorded with the
    # submission rather than collected on a separate form.
    consent_given = models.BooleanField(default=False)
    consented_at = models.DateTimeField(null=True, blank=True)
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
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(consent_given=False) | models.Q(consented_at__isnull=False)
                ),
                name="identity_document_consent_has_timestamp",
            ),
        ]
        indexes = [
            # CP-105 rejects an id_number already linked to a different account,
            # so every submission hits this lookup. It is deliberately NOT a
            # unique constraint: CP-106 lets a rejected submission be replaced,
            # and the same person re-submitting the same ID must stay legal. The
            # uniqueness rule is "one id_number per account", which spans rows
            # and is enforced in the serializer rather than by the database.
            models.Index(fields=["id_number"], name="idx_identity_doc_id_number"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} - {self.document_type.name} ({self.id_number})"
