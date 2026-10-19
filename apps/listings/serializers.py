from rest_framework import serializers

from .models import (
    AvailabilityWindow,
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)


class ListingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingCategory
        fields = ["id", "name"]


class ListingStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingStatus
        fields = ["id", "name"]


class PickupLocationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    class Meta:
        model = PickupLocation
        fields = ["id", "name", "description"]

    def validate_name(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("Location name cannot be blank.")
        return trimmed


class ListingPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingPhoto
        fields = ["id", "file_reference", "uploaded_at"]


class AvailabilityWindowSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityWindow
        fields = ["id", "start_date", "end_date"]


class BlockedDateRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedDateRange
        fields = ["id", "start_date", "end_date", "reason", "created_at"]


class ListingSerializer(serializers.ModelSerializer):
    category = ListingCategorySerializer(read_only=True)
    status = ListingStatusSerializer(read_only=True)
    pickup_location = PickupLocationSerializer(read_only=True)

    lender = serializers.SerializerMethodField()

    photos = ListingPhotoSerializer(many=True, read_only=True)
    availability_windows = AvailabilityWindowSerializer(
        many=True,
        read_only=True,
    )
    blocked_dates = BlockedDateRangeSerializer(
        many=True,
        read_only=True,
    )

    def get_lender(self, obj):
        return {
            "id": obj.lender_id,
            "full_name": obj.lender.full_name,
        }

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
            "blocked_dates",
            "created_at",
            "updated_at",
        ]
