import math
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.constants import (
    DEFAULT_LOGIN_LOCKOUT_MINUTES,
    DEFAULT_LOGIN_LOCKOUT_THRESHOLD,
    LOGIN_LOCKOUT_MINUTES,
    LOGIN_LOCKOUT_THRESHOLD,
)
from apps.core.selectors import get_int_config

from .constants import (
    ALLOWED_IDENTITY_DOCUMENT_CONTENT_TYPES,
    ALLOWED_REGISTRATION_AFFILIATIONS,
    IDENTITY_DOCUMENT_STATUS_PENDING,
    MAX_IDENTITY_DOCUMENT_BYTES,
    PHILIPPINES_MOBILE_REGEX,
    normalize_name,
)
from .models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)
from .services import email_verification_token_generator


def login_lockout_threshold() -> int:
    """Failed logins before lockout, Admin-configurable (CP-103)."""
    return get_int_config(LOGIN_LOCKOUT_THRESHOLD, DEFAULT_LOGIN_LOCKOUT_THRESHOLD)


def login_lockout_minutes() -> int:
    """How long a CP-103 lockout lasts, Admin-configurable."""
    return get_int_config(LOGIN_LOCKOUT_MINUTES, DEFAULT_LOGIN_LOCKOUT_MINUTES)


class UserResponseSerializer(serializers.ModelSerializer):
    """Serializer for exposing user data in API responses (FR1, FR2)."""

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "contact_number",
            "affiliation",
            "account_status",
            "lender_status",
            "email_verified_at",
            "created_at",
        )
        read_only_fields = fields


class UserRegistrationSerializer(serializers.Serializer):
    """
    Serializer for handling user self-registration requests (CP-101).
    Validates required fields, PUP webmail domain, domain-affiliation alignment,
    Philippine mobile number format, and password criteria.
    """

    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
    )
    full_name = serializers.CharField(max_length=255, required=True)
    contact_number = serializers.CharField(max_length=20, required=True)
    affiliation = serializers.ChoiceField(
        choices=User.AffiliationChoices.choices,
        required=True,
    )

    def validate_email(self, value: str) -> str:
        normalized_email = value.strip().lower()

        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError(
                "An account with this email address already exists."
            )

        student_domain = getattr(
            settings, "ALLOWED_STUDENT_EMAIL_DOMAIN", "iskolarngbayan.pup.edu.ph"
        ).lower()
        faculty_domain = getattr(
            settings, "ALLOWED_FACULTY_EMAIL_DOMAIN", "pup.edu.ph"
        ).lower()

        if "@" not in normalized_email:
            raise serializers.ValidationError("Enter a valid email address.")

        domain = normalized_email.split("@")[-1]
        if domain not in (student_domain, faculty_domain):
            raise serializers.ValidationError(
                f"Registration is restricted to PUP webmail addresses "
                f"(@{student_domain} for students, @{faculty_domain} for faculty/staff)."
            )

        return normalized_email

    def validate_contact_number(self, value: str) -> str:
        cleaned_number = value.strip()
        if not PHILIPPINES_MOBILE_REGEX.match(cleaned_number):
            raise serializers.ValidationError(
                "Enter a valid Philippine mobile number (e.g., 09123456789 or +639123456789)."
            )
        return cleaned_number

    def validate_full_name(self, value: str) -> str:
        cleaned_name = value.strip()
        if len(cleaned_name) < 2:
            raise serializers.ValidationError(
                "Full name must be at least 2 characters long."
            )
        return cleaned_name

    def validate_affiliation(self, value: str) -> str:
        if value not in ALLOWED_REGISTRATION_AFFILIATIONS:
            raise serializers.ValidationError(
                "Self-registration is only allowed for Student, Faculty, or Staff."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        password = attrs.get("password")
        password_confirm = attrs.get("password_confirm")

        if password != password_confirm:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )

        # Validate password strength against configured AUTH_PASSWORD_VALIDATORS
        try:
            validate_password(password)
        except DjangoValidationError as err:
            raise serializers.ValidationError({"password": list(err.messages)})

        # Enforce domain-affiliation match server-side
        email = attrs.get("email", "")
        domain = email.split("@")[-1].lower() if "@" in email else ""
        affiliation = attrs.get("affiliation")

        student_domain = getattr(
            settings, "ALLOWED_STUDENT_EMAIL_DOMAIN", "iskolarngbayan.pup.edu.ph"
        ).lower()
        faculty_domain = getattr(
            settings, "ALLOWED_FACULTY_EMAIL_DOMAIN", "pup.edu.ph"
        ).lower()

        if affiliation == User.AffiliationChoices.STUDENT and domain != student_domain:
            raise serializers.ValidationError(
                {
                    "affiliation": (
                        f"Student affiliation requires an @{student_domain} email address."
                    )
                }
            )

        if (
            affiliation
            in (User.AffiliationChoices.FACULTY, User.AffiliationChoices.STAFF)
            and domain != faculty_domain
        ):
            raise serializers.ValidationError(
                {
                    "affiliation": (
                        f"{affiliation} affiliation requires an @{faculty_domain} email address."
                    )
                }
            )

        return attrs


class IdentityDocumentResponseSerializer(serializers.ModelSerializer):
    """
    Submission status for the requesting user (CP-105).

    `document_data` is deliberately absent. FR3 confines the stored document to
    Administrators, and this serializer is the one the mobile client reads, so the
    document bytes must never reach a phone. The user sees that they submitted
    something, not what they submitted.
    """

    document_type = serializers.CharField(source="document_type.name", read_only=True)
    status = serializers.CharField(source="status.name", read_only=True)

    class Meta:
        model = IdentityDocument
        fields = (
            "id",
            "document_type",
            "id_number",
            "status",
            "has_profile_mismatch",
            "consent_given",
            "consented_at",
            "rejection_reason",
            "submitted_at",
            "reviewed_at",
        )
        read_only_fields = fields


class IdentityDocumentSubmissionSerializer(serializers.Serializer):
    """
    Accept an identity document and record the submission (CP-105).

    Handles the four server-side rules the ticket calls for: consent is required
    before anything is stored, an ID number already attached to a different
    account is refused, a name that disagrees with the registration is flagged for
    Admin review rather than rejected, and only a confirmed email may submit.
    """

    document_type = serializers.CharField(max_length=50)
    id_number = serializers.CharField(max_length=100)
    name_on_document = serializers.CharField(max_length=255)
    document_file = serializers.FileField()
    consent_given = serializers.BooleanField()

    def validate_document_type(self, value: str) -> str:
        """Accept the lookup row's name, e.g. "pup_id", as that is friendlier to
        a mobile client than sending a surrogate primary key."""
        normalized = value.strip().lower()
        if not IdentityDocumentType.objects.filter(name=normalized).exists():
            raise serializers.ValidationError("Choose a valid document type.")
        return normalized

    def validate_id_number(self, value: str) -> str:
        """
        Normalise, then enforce "one ID number per account".

        The comparison is case-insensitive because IDs are printed in mixed case
        and typed by hand, so `2024-00123ABC` and `2024-00123abc` are the same
        number. Only *other* accounts block a submission: CP-106 lets the same
        person resubmit after a rejection, and re-sending the same ID has to keep
        working.
        """
        normalized = value.strip().upper()
        if len(normalized) < 2:
            raise serializers.ValidationError("Enter a valid ID number.")

        conflicting = IdentityDocument.objects.filter(
            id_number__iexact=normalized
        ).exclude(user=self.context["request"].user)
        if conflicting.exists():
            raise serializers.ValidationError(
                "This ID number is already linked to another account."
            )
        return normalized

    def validate_document_file(self, file) -> object:
        """Reject the wrong format or an oversized file before any bytes are kept."""
        if file.size > MAX_IDENTITY_DOCUMENT_BYTES:
            max_megabytes = MAX_IDENTITY_DOCUMENT_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                f"Document must be {max_megabytes}MB or smaller."
            )

        content_type = (getattr(file, "content_type", "") or "").lower()
        if content_type not in ALLOWED_IDENTITY_DOCUMENT_CONTENT_TYPES:
            allowed = ", ".join(
                allowed_type.split("/")[-1].upper()
                for allowed_type in ALLOWED_IDENTITY_DOCUMENT_CONTENT_TYPES
            )
            raise serializers.ValidationError(f"Document must be one of: {allowed}.")
        return file

    def validate_consent_given(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "You must consent to your identity document being reviewed "
                "before submitting it."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Cross-field checks, then build the record.

        Order matters: the email check runs before consent is honoured so an
        unverified caller is told to confirm their address instead of being led
        to believe a submission was accepted.
        """
        request = self.context["request"]
        user = request.user

        if not user.is_email_verified:
            raise serializers.ValidationError(
                {"email": "Confirm your email address before submitting a document."}
            )

        document_type = IdentityDocumentType.objects.get(name=attrs["document_type"])
        pending_status = IdentityDocumentStatus.objects.get(
            name=IDENTITY_DOCUMENT_STATUS_PENDING
        )

        # Flag, do not reject: a name that differs from the registration is a
        # reason for CP-106's Admin to check, and the ticket asks for a flag.
        has_mismatch = normalize_name(attrs["name_on_document"]) != normalize_name(
            user.full_name
        )

        document = IdentityDocument(
            user=user,
            document_type=document_type,
            id_number=attrs["id_number"],
            # The upload was already validated for type and size by
            # `document_file`; read it into the row rather than handing it to a
            # storage backend (see IdentityDocument.document_data).
            document_data=attrs["document_file"].read(),
            status=pending_status,
            name_on_document=attrs["name_on_document"].strip(),
            has_profile_mismatch=has_mismatch,
            consent_given=True,
            consented_at=timezone.now(),
        )
        document.save()

        attrs["created_document"] = document
        return attrs


class IdentityDocumentReviewSerializer(serializers.Serializer):
    """
    Validate and process an Administrator's review of an identity document (CP-106).
    """

    action = serializers.ChoiceField(choices=["approve", "reject"])
    rejection_reason = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        action = attrs.get("action")
        rejection_reason = attrs.get("rejection_reason", "").strip()

        if action == "reject" and not rejection_reason:
            raise serializers.ValidationError(
                {"rejection_reason": "A reason is required when rejecting a document."}
            )

        document = self.instance
        if (
            document is not None
            and document.status.name != IDENTITY_DOCUMENT_STATUS_PENDING
        ):
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"This document has already been reviewed (current status: {document.status.name})."
                    )
                }
            )

        attrs["rejection_reason"] = rejection_reason
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    """
    Validate a confirmation link and mark the account verified (CP-102).

    Failures are deliberately indistinguishable from one another. Whether the
    `uid` names nobody, or the token is forged, or it simply aged out, the
    caller gets the same message -- otherwise this endpoint becomes a probe for
    which user ids exist and which have already confirmed.
    """

    uid = serializers.CharField()
    token = serializers.CharField()

    default_error_messages = {
        "invalid_link": "This verification link is invalid or has expired."
    }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            user_pk = urlsafe_base64_decode(attrs["uid"]).decode()
            user = User.objects.get(pk=user_pk)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise serializers.ValidationError(
                {"detail": self.error_messages["invalid_link"]}
            )

        if not email_verification_token_generator().check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"detail": self.error_messages["invalid_link"]}
            )

        attrs["verified_user"] = user
        return attrs


class LoginSerializer(serializers.Serializer):
    """
    Exchange credentials for a token pair (CP-103).

    The order of the checks below is the security-relevant part:

    1. An unknown address gets the same message as a wrong password, and costs a
       comparable amount of time, so the endpoint cannot be used to discover which
       addresses are registered.
    2. An active lockout is reported before the password is even checked.
    3. Account-state refusals (suspended, banned, unconfirmed email) happen only
       *after* the password is proven. The ticket wants a clear message for these,
       and gating it behind a correct password means the message is only ever seen
       by the account's real owner.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    default_error_messages = {
        "invalid_credentials": "Invalid email or password.",
        "locked_out": "Too many failed login attempts. Try again in {minutes} minute(s).",
        "suspended": "This account is suspended. Please contact an administrator.",
        "banned": "This account is banned. Please contact an administrator.",
        "inactive": "This account is not active.",
        "unverified_email": "Confirm your email address before logging in. Check your inbox for the verification link.",
    }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Authenticate, or explain why not.

        Every refusal below raises `AuthenticationFailed`, so the caller gets a
        single `detail` string at HTTP 401 and a machine-readable `code` to
        branch on (`invalid_credentials`, `locked_out`, `suspended`, `banned`,
        `unverified_email`). The codes are safe to expose: the ones that describe
        account state are only reachable *after* the password is proven.
        """
        email = attrs["email"].strip().lower()
        password = attrs["password"]

        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            # Burn roughly the same time a real password check would take, so a
            # missing account is not measurably faster than a wrong password.
            User().set_password(password)
            raise AuthenticationFailed(
                self.error_messages["invalid_credentials"], code="invalid_credentials"
            )

        if user.is_locked_out:
            minutes_remaining = max(
                1, math.ceil((user.locked_until - timezone.now()).total_seconds() / 60)
            )
            raise AuthenticationFailed(
                self.error_messages["locked_out"].format(minutes=minutes_remaining),
                code="locked_out",
            )

        if not user.check_password(password):
            self._record_failed_attempt(user)
            raise AuthenticationFailed(
                self.error_messages["invalid_credentials"], code="invalid_credentials"
            )

        # Password proven -- from here on, anything said reaches the real owner.
        if not user.is_active:
            raise AuthenticationFailed(self.error_messages["inactive"], code="inactive")
        if user.account_status == User.AccountStatusChoices.SUSPENDED:
            raise AuthenticationFailed(
                self.error_messages["suspended"], code="suspended"
            )
        if user.account_status == User.AccountStatusChoices.BANNED:
            raise AuthenticationFailed(self.error_messages["banned"], code="banned")
        if not user.is_email_verified:
            raise AuthenticationFailed(
                self.error_messages["unverified_email"], code="unverified_email"
            )

        self._clear_failed_attempts(user)

        refresh = RefreshToken.for_user(user)

        # SIMPLE_JWT sets UPDATE_LAST_LOGIN, but its hook only fires through the
        # serializer it ships with, so a hand-rolled login has to do it here.
        user.last_login = timezone.now()
        user.save(update_fields=["last_login", "updated_at"])

        attrs["user"] = user
        attrs["tokens"] = {"refresh": str(refresh), "access": str(refresh.access_token)}
        return attrs

    def _record_failed_attempt(self, user: User) -> None:
        """
        Count a bad password and start a lockout once the threshold is reached.

        The counter is bumped with an F() expression so concurrent attempts
        cannot overwrite each other into a lost update, then re-read before the
        comparison. Once the threshold is hit the counter resets, which gives the
        user a fresh set of attempts after the lockout expires instead of
        locking them out permanently on the fifth bad try forever.
        """
        User.objects.filter(pk=user.pk).update(
            failed_login_attempts=F("failed_login_attempts") + 1
        )
        user.refresh_from_db(fields=["failed_login_attempts"])

        if user.failed_login_attempts < login_lockout_threshold():
            return

        lockout_minutes = login_lockout_minutes()
        user.locked_until = timezone.now() + timedelta(minutes=lockout_minutes)
        user.failed_login_attempts = 0
        user.save(update_fields=["locked_until", "failed_login_attempts", "updated_at"])

    def _clear_failed_attempts(self, user: User) -> None:
        """A correct password ends the consecutive-failure streak."""
        if user.failed_login_attempts == 0 and user.locked_until is None:
            return
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_attempts", "locked_until", "updated_at"])


class RefreshSerializer(serializers.Serializer):
    """
    Swap a refresh token for a fresh access token (CP-103).

    SimpleJWT's own `TokenRefreshSerializer` looks the token's user up with a bare
    `objects.get()` and does not catch `DoesNotExist`
    (`rest_framework_simplejwt/serializers.py`), so refreshing a token whose
    account was removed -- which CP-102 does deliberately to unverified users --
    raises an unhandled 500. Catching it here turns that into the 401 it should
    have been all along.
    """

    refresh = serializers.CharField()
    token_class = RefreshToken

    default_error_messages = {
        "no_active_account": "This account is no longer active. Please log in again.",
        "invalid_token": "Invalid or expired refresh token.",
    }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            refresh = self.token_class(attrs["refresh"])
        except TokenError:
            raise AuthenticationFailed(
                self.error_messages["invalid_token"], code="invalid_token"
            )

        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        user = None
        if user_id:
            user = User.objects.filter(pk=user_id).first()

        if user is None or not user.is_active:
            raise AuthenticationFailed(
                self.error_messages["no_active_account"], code="no_active_account"
            )

        data: dict[str, Any] = {"access": str(refresh.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            refresh.blacklist()
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()
            data["refresh"] = str(refresh)

        return data


class LogoutSerializer(serializers.Serializer):
    """Blacklist a refresh token so the session cannot be continued (CP-103)."""

    refresh = serializers.CharField()

    default_error_messages = {"invalid_token": "Invalid or expired refresh token."}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            RefreshToken(attrs["refresh"]).blacklist()
        except TokenError:
            raise AuthenticationFailed(
                self.error_messages["invalid_token"], code="invalid_token"
            )
        return {}
