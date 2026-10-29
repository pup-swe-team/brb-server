"""Serializers for order status overrides and unreturned case administration (CP-506)."""

from __future__ import annotations

from rest_framework import serializers

from .constants import ALL_ORDER_STATUSES, CLOSING_UNRETURNED_CASE_STATUSES
from .models import Order, OrderStatusOverride, UnreturnedCase


class UnreturnedCaseSummarySerializer(serializers.ModelSerializer):
    """Summary serializer for listing Admin UnreturnedCase records (CP-506)."""

    order_id = serializers.IntegerField(read_only=True)
    order_status = serializers.CharField(source="order.status.name", read_only=True)
    listing_id = serializers.IntegerField(source="order.listing_id", read_only=True)
    listing_title = serializers.CharField(source="order.listing.title", read_only=True)
    borrower_id = serializers.IntegerField(source="order.borrower_id", read_only=True)
    borrower_name = serializers.CharField(
        source="order.borrower.full_name", read_only=True
    )
    borrower_email = serializers.EmailField(
        source="order.borrower.email", read_only=True
    )
    lender_id = serializers.IntegerField(
        source="order.listing.lender_id", read_only=True
    )
    lender_name = serializers.CharField(
        source="order.listing.lender.full_name", read_only=True
    )
    status = serializers.CharField(source="status.name", read_only=True)
    escalated_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = UnreturnedCase
        fields = [
            "id",
            "order_id",
            "order_status",
            "listing_id",
            "listing_title",
            "borrower_id",
            "borrower_name",
            "borrower_email",
            "lender_id",
            "lender_name",
            "status",
            "escalated_at",
            "escalated_by_id",
            "resolution_notes",
            "created_at",
            "updated_at",
        ]


class EscalateUnreturnedCaseSerializer(serializers.Serializer):
    """Input payload for escalating an UnreturnedCase to OSS / Campus Security (CP-506)."""

    resolution_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        write_only=True,
    )

    def validate(self, attrs: dict) -> dict:
        attrs["resolution_notes"] = (
            attrs.get("resolution_notes") or attrs.get("notes") or ""
        ).strip()
        return attrs


class CloseUnreturnedCaseSerializer(serializers.Serializer):
    """Input payload for closing an UnreturnedCase as 'returned' or 'unresolved' (CP-506)."""

    status = serializers.CharField(required=False, trim_whitespace=True)
    outcome = serializers.CharField(
        required=False, trim_whitespace=True, write_only=True
    )
    resolution_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        write_only=True,
    )

    def validate(self, attrs: dict) -> dict:
        raw_status = (attrs.get("status") or attrs.get("outcome") or "").strip().lower()
        if raw_status not in CLOSING_UNRETURNED_CASE_STATUSES:
            raise serializers.ValidationError(
                {
                    "status": (
                        "Case closing status must be one of: "
                        f"{', '.join(CLOSING_UNRETURNED_CASE_STATUSES)}."
                    )
                }
            )
        attrs["status"] = raw_status
        attrs["resolution_notes"] = (
            attrs.get("resolution_notes") or attrs.get("notes") or ""
        ).strip()
        return attrs


class OrderStatusOverrideInputSerializer(serializers.Serializer):
    """Input payload for Admin manual order status correction (CP-506, FR8, FR14)."""

    new_status = serializers.CharField(required=False, trim_whitespace=True)
    status = serializers.CharField(
        required=False, trim_whitespace=True, write_only=True
    )
    reason = serializers.CharField(
        required=True, allow_blank=False, trim_whitespace=True
    )

    def validate(self, attrs: dict) -> dict:
        target = (attrs.get("new_status") or attrs.get("status") or "").strip().lower()
        if not target:
            raise serializers.ValidationError(
                {"new_status": "A target order status is required."}
            )
        if target not in ALL_ORDER_STATUSES:
            raise serializers.ValidationError(
                {
                    "new_status": (
                        f"Invalid order status '{target}'. Must be one of: "
                        f"{', '.join(ALL_ORDER_STATUSES)}."
                    )
                }
            )
        cleaned_reason = (attrs.get("reason") or "").strip()
        if not cleaned_reason:
            raise serializers.ValidationError(
                {"reason": "A reason is required for manual status correction."}
            )
        attrs["new_status"] = target
        attrs["reason"] = cleaned_reason
        return attrs


class OrderStatusOverrideSerializer(serializers.ModelSerializer):
    """Serialized representation of an OrderStatusOverride audit log record."""

    order_id = serializers.IntegerField(read_only=True)
    admin_id = serializers.IntegerField(read_only=True)
    admin_name = serializers.CharField(source="admin.full_name", read_only=True)

    class Meta:
        model = OrderStatusOverride
        fields = [
            "id",
            "order_id",
            "admin_id",
            "admin_name",
            "previous_status",
            "new_status",
            "reason",
            "overridden_at",
        ]


class OrderStatusOverrideResultSerializer(serializers.ModelSerializer):
    """Response payload returned after an Admin manual order status correction."""

    listing_id = serializers.IntegerField(read_only=True)
    borrower_id = serializers.IntegerField(read_only=True)
    lender_id = serializers.IntegerField(source="listing.lender_id", read_only=True)
    status = serializers.CharField(source="status.name", read_only=True)
    override = OrderStatusOverrideSerializer(read_only=True)

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
            "override",
        ]
