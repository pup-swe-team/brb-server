import json
from datetime import date
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.reviews.models import Review
from apps.users.models import User

from .constants import (
    ALLOWED_LISTING_PHOTO_CONTENT_TYPES,
    MAX_LISTING_PHOTO_BYTES,
)
from .models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)
from .selectors import get_lender_rating_stats, get_listing_reviews
from .services import create_listing


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
    """Serializer for publishing a resource listing (FR6, FR7, CP-401)."""

    title = serializers.CharField(max_length=200, required=True)
    description = serializers.CharField(required=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=ListingCategory.objects.all(),
        required=True,
    )
    condition = serializers.CharField(max_length=50, required=True)
    pickup_location = serializers.PrimaryKeyRelatedField(
        queryset=PickupLocation.objects.all(),
        required=True,
    )
    rate_per_day = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    is_ownership_confirmed = serializers.BooleanField(required=True)

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

    def validate_is_ownership_confirmed(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "You must confirm ownership or the right to lend the item before publishing."
            )
        return value

    def validate_pickup_location(self, value: PickupLocation) -> PickupLocation:
        if value.deleted_at is not None:
            raise serializers.ValidationError(
                "Selected pickup location is not available."
            )
        return value

    def _parse_date(self, val: Any) -> date:
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            try:
                return date.fromisoformat(val.strip())
            except ValueError:
                raise serializers.ValidationError(
                    f"Date '{val}' must be in YYYY-MM-DD format."
                )
        raise serializers.ValidationError("Invalid date value.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")

        # 1. Extract and validate photos
        photos = []
        if request and request.FILES:
            photos = request.FILES.getlist("photos")
        if not photos and "photos" in self.initial_data:
            initial_photos = self.initial_data.get("photos")
            if isinstance(initial_photos, list):
                photos = initial_photos
            elif initial_photos:
                photos = [initial_photos]

        if not photos:
            raise serializers.ValidationError(
                {"photos": "At least one photo is required."}
            )

        for photo in photos:
            if getattr(photo, "size", 0) > MAX_LISTING_PHOTO_BYTES:
                max_mb = MAX_LISTING_PHOTO_BYTES // (1024 * 1024)
                raise serializers.ValidationError(
                    {"photos": f"Image must be {max_mb}MB or smaller."}
                )

            content_type = (getattr(photo, "content_type", "") or "").lower()
            if content_type and content_type not in ALLOWED_LISTING_PHOTO_CONTENT_TYPES:
                allowed = ", ".join(
                    t.split("/")[-1].upper()
                    for t in ALLOWED_LISTING_PHOTO_CONTENT_TYPES
                )
                raise serializers.ValidationError(
                    {"photos": f"Image must be one of: {allowed}."}
                )

        attrs["photos"] = photos

        # 2. Extract and validate availability windows
        raw_windows = self.initial_data.get("availability_windows")
        windows_data = []

        if isinstance(raw_windows, str):
            try:
                windows_data = json.loads(raw_windows)
            except (json.JSONDecodeError, TypeError):
                raise serializers.ValidationError(
                    {
                        "availability_windows": "Invalid JSON format for availability windows."
                    }
                )
        elif isinstance(raw_windows, list):
            windows_data = raw_windows
        elif "start_date" in self.initial_data and "end_date" in self.initial_data:
            windows_data = [
                {
                    "start_date": self.initial_data["start_date"],
                    "end_date": self.initial_data["end_date"],
                }
            ]

        if not windows_data or not isinstance(windows_data, list):
            raise serializers.ValidationError(
                {
                    "availability_windows": "At least one availability date window is required."
                }
            )

        parsed_windows = []
        today = timezone.now().date()

        for win in windows_data:
            if (
                not isinstance(win, dict)
                or "start_date" not in win
                or "end_date" not in win
            ):
                raise serializers.ValidationError(
                    {
                        "availability_windows": "Each availability window must have start_date and end_date."
                    }
                )
            start_d = self._parse_date(win["start_date"])
            end_d = self._parse_date(win["end_date"])

            if start_d > end_d:
                raise serializers.ValidationError(
                    {
                        "availability_windows": "Start date must be before or equal to end date."
                    }
                )

            if start_d < today:
                raise serializers.ValidationError(
                    {
                        "availability_windows": "Availability dates cannot be in the past."
                    }
                )

            parsed_windows.append({"start_date": start_d, "end_date": end_d})

        attrs["availability_windows"] = parsed_windows
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Listing:
        request = self.context.get("request")
        lender = request.user

        return create_listing(
            lender=lender,
            title=validated_data["title"],
            description=validated_data["description"],
            category=validated_data["category"],
            condition=validated_data["condition"],
            pickup_location=validated_data["pickup_location"],
            rate_per_day=validated_data.get("rate_per_day"),
            is_ownership_confirmed=validated_data["is_ownership_confirmed"],
            photos=validated_data["photos"],
            availability_windows=validated_data["availability_windows"],
        )
