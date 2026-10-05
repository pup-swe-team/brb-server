from typing import Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .constants import ALLOWED_REGISTRATION_AFFILIATIONS, PHILIPPINES_MOBILE_REGEX
from .models import User


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
