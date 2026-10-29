"""Serializers for authentication code generation and verification (CP-504, CP-505)."""

from __future__ import annotations

import re

from rest_framework import serializers

from apps.orders.models import Order

from .constants import AUTH_CODE_LENGTH
from .models import AuthCode, AuthCodeAttempt

SIX_DIGIT_CODE_REGEX = re.compile(rf"^\d{{{AUTH_CODE_LENGTH}}}$")


class AuthCodeResponseSerializer(serializers.ModelSerializer):
    """Serialized representation of a generated or consumed AuthCode."""

    order_id = serializers.IntegerField(read_only=True)
    code_type = serializers.CharField(source="code_type.name", read_only=True)
    auth_status = serializers.CharField(source="auth_status.name", read_only=True)

    class Meta:
        model = AuthCode
        fields = [
            "id",
            "order_id",
            "code_type",
            "code_value",
            "auth_status",
            "generated_at",
            "expires_at",
            "used_at",
        ]


class HandoverCodeVerifyInputSerializer(serializers.Serializer):
    """Input payload for verifying a 6-digit handover authentication code (CP-504)."""

    code = serializers.CharField(required=False, trim_whitespace=True)
    code_value = serializers.CharField(
        required=False, trim_whitespace=True, write_only=True
    )

    def validate(self, attrs: dict) -> dict:
        raw_code = (attrs.get("code") or attrs.get("code_value") or "").strip()
        if not raw_code:
            raise serializers.ValidationError(
                {"code": "A 6-digit authentication code is required."}
            )
        if not SIX_DIGIT_CODE_REGEX.match(raw_code):
            raise serializers.ValidationError(
                {"code": "Authentication code must be exactly 6 numeric digits."}
            )
        attrs["code"] = raw_code
        return attrs


class ReturnCodeVerifyInputSerializer(HandoverCodeVerifyInputSerializer):
    """
    Input payload for verifying a 6-digit return authentication code (CP-505).
    Supports optional damage/missing item flagging that auto-transitions the order
    to Disputed instead of Completed.
    """

    flagged = serializers.BooleanField(required=False, default=False)
    has_damage = serializers.BooleanField(
        required=False, default=False, write_only=True
    )
    damage_flagged = serializers.BooleanField(
        required=False, default=False, write_only=True
    )
    dispute_description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        write_only=True,
    )

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        attrs["flagged"] = bool(
            attrs.get("flagged")
            or attrs.get("has_damage")
            or attrs.get("damage_flagged")
        )
        attrs["dispute_description"] = (
            attrs.get("dispute_description") or attrs.get("description") or ""
        ).strip()
        return attrs


class HandoverVerificationResponseSerializer(serializers.ModelSerializer):
    """Response payload returned when a handover or return code transitions an Order."""

    listing_id = serializers.IntegerField(read_only=True)
    borrower_id = serializers.IntegerField(read_only=True)
    lender_id = serializers.IntegerField(source="listing.lender_id", read_only=True)
    status = serializers.CharField(source="status.name", read_only=True)
    auth_code = AuthCodeResponseSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "listing_id",
            "borrower_id",
            "lender_id",
            "start_date",
            "end_date",
            "status",
            "updated_at",
            "auth_code",
        ]


class ReturnVerificationResponseSerializer(HandoverVerificationResponseSerializer):
    """Response payload returned when a return code is verified (CP-505)."""

    returned_status = serializers.CharField(default="returned", read_only=True)
    dispute_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta(HandoverVerificationResponseSerializer.Meta):
        fields = [
            *HandoverVerificationResponseSerializer.Meta.fields,
            "returned_status",
            "dispute_id",
        ]


class AuthCodeAttemptSerializer(serializers.ModelSerializer):
    """Read-only serializer for code attempt logs (used in Admin review dossiers)."""

    attempted_by_id = serializers.IntegerField(read_only=True)
    attempted_by_email = serializers.EmailField(
        source="attempted_by.email", read_only=True
    )
    attempted_by_name = serializers.CharField(
        source="attempted_by.full_name", read_only=True
    )

    class Meta:
        model = AuthCodeAttempt
        fields = [
            "id",
            "code_id",
            "attempted_by_id",
            "attempted_by_email",
            "attempted_by_name",
            "was_successful",
            "attempted_at",
        ]
