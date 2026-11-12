"""Serializers for reporting users, listings, reviews, and messages (CP-901)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .constants import (
    ALL_REPORT_TARGETS,
    REPORT_TARGET_LISTING,
    REPORT_TARGET_MESSAGE,
    REPORT_TARGET_REVIEW,
    REPORT_TARGET_USER,
)
from .models import (
    ListingReport,
    MessageReport,
    ReviewReport,
    UserReport,
)


class ReportCategoryItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class BaseTargetedReportSerializer(serializers.Serializer):
    """Base input serializer accepting category by ID or name and non-blank description."""

    category = serializers.JSONField(required=False)
    category_id = serializers.IntegerField(min_value=1, required=False)
    description = serializers.CharField(trim_whitespace=True, allow_blank=False)

    def _extract_category(self, attrs: dict[str, Any]) -> int | str:
        cat = attrs.get("category")
        if cat is None or cat == "":
            cat = attrs.get("category_id")
        if cat is None or cat == "":
            raise serializers.ValidationError(
                {"category": "A report category or category_id is required."}
            )
        if not isinstance(cat, (int, str)):
            raise serializers.ValidationError(
                {"category": "Category must be an integer ID or category name string."}
            )
        return cat


class UnifiedReportCreateSerializer(BaseTargetedReportSerializer):
    target_type = serializers.ChoiceField(choices=ALL_REPORT_TARGETS)
    target_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    order = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["resolved_category"] = self._extract_category(attrs)
        attrs["resolved_order_id"] = attrs.get("order_id") or attrs.get("order")
        return attrs


class UserReportCreateSerializer(BaseTargetedReportSerializer):
    target_user_id = serializers.IntegerField(min_value=1, required=False)
    target_user = serializers.IntegerField(min_value=1, required=False)
    target_id = serializers.IntegerField(min_value=1, required=False)
    order_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    order = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        target_id = (
            self.context.get("target_id")
            or attrs.get("target_user_id")
            or attrs.get("target_user")
            or attrs.get("target_id")
        )
        if not target_id:
            raise serializers.ValidationError(
                {"target_user_id": "target_user_id is required."}
            )
        attrs["resolved_target_id"] = int(target_id)
        attrs["resolved_category"] = self._extract_category(attrs)
        attrs["resolved_order_id"] = attrs.get("order_id") or attrs.get("order")
        return attrs


class ListingReportCreateSerializer(BaseTargetedReportSerializer):
    target_listing_id = serializers.IntegerField(min_value=1, required=False)
    target_listing = serializers.IntegerField(min_value=1, required=False)
    target_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        target_id = (
            self.context.get("target_id")
            or attrs.get("target_listing_id")
            or attrs.get("target_listing")
            or attrs.get("target_id")
        )
        if not target_id:
            raise serializers.ValidationError(
                {"target_listing_id": "target_listing_id is required."}
            )
        attrs["resolved_target_id"] = int(target_id)
        attrs["resolved_category"] = self._extract_category(attrs)
        return attrs


class ReviewReportCreateSerializer(BaseTargetedReportSerializer):
    target_review_id = serializers.IntegerField(min_value=1, required=False)
    target_review = serializers.IntegerField(min_value=1, required=False)
    target_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        target_id = (
            self.context.get("target_id")
            or attrs.get("target_review_id")
            or attrs.get("target_review")
            or attrs.get("target_id")
        )
        if not target_id:
            raise serializers.ValidationError(
                {"target_review_id": "target_review_id is required."}
            )
        attrs["resolved_target_id"] = int(target_id)
        attrs["resolved_category"] = self._extract_category(attrs)
        return attrs


class MessageReportCreateSerializer(BaseTargetedReportSerializer):
    target_message_id = serializers.IntegerField(min_value=1, required=False)
    target_message = serializers.IntegerField(min_value=1, required=False)
    target_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        target_id = (
            self.context.get("target_id")
            or attrs.get("target_message_id")
            or attrs.get("target_message")
            or attrs.get("target_id")
        )
        if not target_id:
            raise serializers.ValidationError(
                {"target_message_id": "target_message_id is required."}
            )
        attrs["resolved_target_id"] = int(target_id)
        attrs["resolved_category"] = self._extract_category(attrs)
        return attrs


def serialize_report(
    report: UserReport | ListingReport | ReviewReport | MessageReport,
) -> dict[str, Any]:
    """Serialize any of the four report model instances into a consistent response payload."""
    if isinstance(report, UserReport):
        target_type = REPORT_TARGET_USER
        target_id = report.target_user_id
        extra = {
            "target_user_id": report.target_user_id,
            "order_id": report.order_id,
        }
    elif isinstance(report, ListingReport):
        target_type = REPORT_TARGET_LISTING
        target_id = report.target_listing_id
        extra = {"target_listing_id": report.target_listing_id}
    elif isinstance(report, ReviewReport):
        target_type = REPORT_TARGET_REVIEW
        target_id = report.target_review_id
        extra = {"target_review_id": report.target_review_id}
    else:
        target_type = REPORT_TARGET_MESSAGE
        target_id = report.target_message_id
        extra = {"target_message_id": report.target_message_id}

    return {
        "id": report.pk,
        "target_type": target_type,
        "target_id": target_id,
        "reporter_id": report.reporter_id,
        "category_id": report.category_id,
        "category": report.category.name,
        "description": report.description,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        **extra,
    }
