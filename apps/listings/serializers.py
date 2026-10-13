from typing import Any

from rest_framework import serializers

from apps.reviews.models import Review
from apps.users.models import User

from .models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)
from .selectors import get_lender_rating_stats, get_listing_reviews


class ListingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingCategory
        fields = ["id", "name"]


class ListingStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingStatus
        fields = ["id", "name"]


class PickupLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupLocation
        fields = ["id", "name"]


class ListingPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingPhoto
        fields = ["id", "file_reference", "uploaded_at"]


class AvailabilityWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityWindow
        fields = ["id", "start_date", "end_date"]


class ReviewerSummarySerializer(serializers.ModelSerializer):
    """Minimal representation of a reviewer (FR9, CP-303)."""

    class Meta:
        model = User
        fields = ["id", "full_name", "photo"]
        read_only_fields = fields


class ListingReviewSerializer(serializers.ModelSerializer):
    """Review details for a specific listing (CP-303)."""

    reviewer = ReviewerSummarySerializer(read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "rating",
            "comment",
            "created_at",
            "reviewer",
        ]
        read_only_fields = fields


class LenderSummarySerializer(serializers.ModelSerializer):
    """Lender profile summary with aggregated reputation stats (CP-303, CP-304)."""

    rating_average = serializers.SerializerMethodField()
    total_reviews = serializers.SerializerMethodField()

    def _get_stats(self, obj: User) -> dict[str, Any]:
        if not hasattr(obj, "_cached_rating_stats"):
            obj._cached_rating_stats = get_lender_rating_stats(obj)
        return obj._cached_rating_stats

    def get_rating_average(self, obj: User) -> float | None:
        return self._get_stats(obj)["rating_average"]

    def get_total_reviews(self, obj: User) -> int:
        return self._get_stats(obj)["total_reviews"]

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "photo",
            "affiliation",
            "bio",
            "rating_average",
            "total_reviews",
        ]
        read_only_fields = fields


class ListingSerializer(serializers.ModelSerializer):
    category = ListingCategorySerializer(read_only=True)
    status = ListingStatusSerializer(read_only=True)
    pickup_location = PickupLocationSerializer(read_only=True)
    lender = LenderSummarySerializer(read_only=True)
    photos = ListingPhotoSerializer(many=True, read_only=True)
    availability_windows = AvailabilityWindowSerializer(
        many=True,
        read_only=True,
    )
    reviews = serializers.SerializerMethodField()

    def get_reviews(self, obj: Listing) -> list[dict[str, Any]]:
        reviews_qs = get_listing_reviews(obj)
        return ListingReviewSerializer(
            reviews_qs,
            many=True,
            context=self.context,
        ).data

    class Meta:
        model = Listing
        fields = [
            "id",
            "title",
            "description",
            "condition",
            "rate_per_day",
            "is_ownership_confirmed",
            "lender",
            "category",
            "pickup_location",
            "status",
            "photos",
            "availability_windows",
            "reviews",
            "created_at",
            "updated_at",
        ]


class ListingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = [
            "title",
            "description",
            "condition",
            "rate_per_day",
            "is_ownership_confirmed",
            "category",
            "pickup_location",
        ]
