"""Serializers for mutual reviews and ratings (CP-601)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.reports.models import ReviewReport
from apps.users.models import User

from .models import Review
from .selectors import get_user_rating_stats


class ReviewUserSummarySerializer(serializers.ModelSerializer):
    """Minimal user summary for review payloads."""

    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "photo", "is_verified"]
        read_only_fields = fields

    def get_is_verified(self, obj: User) -> bool:
        return obj.has_verified_identity()


class ReviewCreateSerializer(serializers.Serializer):
    """Input serializer for creating a review on a completed order."""

    order_id = serializers.IntegerField(min_value=1, required=False)
    order = serializers.IntegerField(min_value=1, required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
    )

    def validate(self, attrs):
        order_id = (
            self.context.get("order_id") or attrs.get("order_id") or attrs.get("order")
        )
        if not order_id:
            raise serializers.ValidationError(
                {"order_id": "An order_id is required to submit a review."}
            )
        attrs["resolved_order_id"] = int(order_id)
        return attrs


class ReviewResponseSerializer(serializers.ModelSerializer):
    """Output serializer for a review including updated reviewee rating stats and report action link."""

    order_id = serializers.IntegerField(read_only=True)
    order = serializers.SerializerMethodField()
    reviewer_id = serializers.IntegerField(read_only=True)
    reviewer = ReviewUserSummarySerializer(read_only=True)
    reviewer_name = serializers.CharField(source="reviewer.full_name", read_only=True)
    reviewee_id = serializers.IntegerField(read_only=True)
    reviewee_name = serializers.SerializerMethodField()
    reviewee_average_rating = serializers.SerializerMethodField()
    reviewee_review_count = serializers.SerializerMethodField()
    listing_id = serializers.SerializerMethodField()
    listing_title = serializers.SerializerMethodField()
    item_title = serializers.SerializerMethodField()
    can_report = serializers.SerializerMethodField()
    report_url = serializers.SerializerMethodField()
    target_role = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "order_id",
            "order",
            "listing_id",
            "listing_title",
            "item_title",
            "reviewer_id",
            "reviewer",
            "reviewer_name",
            "reviewee_id",
            "reviewee_name",
            "rating",
            "comment",
            "created_at",
            "edited_at",
            "reviewee_average_rating",
            "reviewee_review_count",
            "can_report",
            "report_url",
            "target_role",
            "role",
        ]
        read_only_fields = fields

    def _get_reviewee_stats(self, obj: Review) -> dict:
        if not hasattr(obj, "_reviewee_stats"):
            obj._reviewee_stats = get_user_rating_stats(obj.reviewee_id)
        return obj._reviewee_stats

    def get_order(self, obj: Review) -> dict[str, Any]:
        return {
            "id": obj.order_id,
            "listing_id": obj.order.listing_id if obj.order_id else None,
            "listing_title": self.get_listing_title(obj),
            "item_title": self.get_listing_title(obj),
        }

    def get_listing_id(self, obj: Review) -> int | None:
        return obj.order.listing_id if obj.order_id else None

    def get_listing_title(self, obj: Review) -> str:
        if obj.order and getattr(obj.order, "listing", None):
            return obj.order.listing.title
        return ""

    def get_item_title(self, obj: Review) -> str:
        return self.get_listing_title(obj)

    def get_reviewee_name(self, obj: Review) -> str:
        return obj.reviewee.full_name

    def get_reviewee_average_rating(self, obj: Review) -> float | None:
        return self._get_reviewee_stats(obj)["average_rating"]

    def get_reviewee_review_count(self, obj: Review) -> int:
        return self._get_reviewee_stats(obj)["review_count"]

    def get_can_report(self, obj: Review) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.pk == obj.reviewer_id:
            return False
        return not ReviewReport.objects.filter(
            reporter_id=user.pk,
            target_review_id=obj.pk,
        ).exists()

    def get_target_role(self, obj: Review) -> str:
        """FE-BUG-4009: role of the reviewee in the order ('borrower' or 'lender')."""
        if obj.reviewer_id == obj.order.borrower_id:
            return "lender"
        return "borrower"

    def get_role(self, obj: Review) -> str:
        return self.get_target_role(obj)

    def get_report_url(self, obj: Review) -> str:
        return f"/api/v1/reviews/{obj.pk}/report/"
