import json
import re
from datetime import date, timedelta
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.reviews.models import Review
from apps.users.models import User

from .constants import (
    ALLOWED_LISTING_PHOTO_CONTENT_TYPES,
    LISTING_STATUS_DELETED,
    MAX_LISTING_PHOTO_BYTES,
)
from .models import (
    AvailabilityWindow,
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)
from .selectors import get_lender_rating_stats, get_listing_reviews
from .services import create_listing, update_listing


def _sniff_photo_content_type(head: bytes) -> str:
    """Infer the image type from file bytes; "" when no supported signature matches."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _extract_and_validate_photos(serializer: serializers.BaseSerializer) -> list[Any]:
    """Pull photos from the request and validate size plus real content by magic bytes."""
    request = serializer.context.get("request")
    photos: list[Any] = []
    photo_keys = ("photos", "photo", "photos[]", "image", "images")

    if request and request.FILES:
        for key in photo_keys:
            extracted = request.FILES.getlist(key)
            if extracted:
                photos.extend(extracted)
                break
    if not photos and serializer.initial_data:
        for key in photo_keys:
            if key in serializer.initial_data:
                initial_photos = serializer.initial_data.get(key)
                if isinstance(initial_photos, list):
                    photos.extend(initial_photos)
                elif initial_photos:
                    photos.append(initial_photos)
                if photos:
                    break

    allowed = ", ".join(
        t.split("/")[-1].upper() for t in ALLOWED_LISTING_PHOTO_CONTENT_TYPES
    )
    valid_photos: list[Any] = []
    for photo in photos:
        if not isinstance(photo, UploadedFile):
            if isinstance(photo, str):
                continue
            raise serializers.ValidationError(
                {"photos": "Photos must be uploaded as image files."}
            )
        if photo.size > MAX_LISTING_PHOTO_BYTES:
            max_mb = MAX_LISTING_PHOTO_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                {"photos": f"Image must be {max_mb}MB or smaller."}
            )
        photo.seek(0)
        head = photo.read(16)
        photo.seek(0)
        if _sniff_photo_content_type(head) not in ALLOWED_LISTING_PHOTO_CONTENT_TYPES:
            raise serializers.ValidationError(
                {"photos": f"Image must be one of: {allowed}."}
            )
        valid_photos.append(photo)
    return valid_photos


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


class BlockedDateRangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedDateRange
        fields = ["id", "start_date", "end_date", "reason", "created_at"]


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
    blocked_dates = BlockedDateRangeSerializer(
        many=True,
        read_only=True,
    )

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
            "blocked_dates",
            "created_at",
            "updated_at",
        ]


class ListingSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)
    category = serializers.IntegerField(required=False)
    condition = serializers.CharField(required=False, allow_blank=True)
    pickup_location = serializers.IntegerField(required=False)
    min_price = serializers.DecimalField(
        required=False, max_digits=10, decimal_places=2, min_value=0
    )
    max_price = serializers.DecimalField(
        required=False, max_digits=10, decimal_places=2, min_value=0
    )
    free_only = serializers.BooleanField(required=False, default=False)
    available_from = serializers.DateField(required=False)
    available_to = serializers.DateField(required=False)
    sort = serializers.ChoiceField(
        choices=[
            "created_at",
            "-created_at",
            "rate_per_day",
            "-rate_per_day",
            "title",
            "-title",
        ],
        required=False,
    )


class ListingSearchResultSerializer(serializers.ModelSerializer):
    category = ListingCategorySerializer(read_only=True)
    pickup_location = PickupLocationSerializer(read_only=True)
    status = ListingStatusSerializer(read_only=True)
    lender = serializers.SerializerMethodField()
    photos = ListingPhotoSerializer(many=True, read_only=True)
    availability_windows = AvailabilityWindowSerializer(many=True, read_only=True)
    active_orders = serializers.SerializerMethodField()

    def get_lender(self, obj: Listing) -> dict:
        return {
            "id": obj.lender_id,
            "full_name": obj.lender.full_name,
            "photo": obj.lender.photo.url if obj.lender.photo else None,
        }

    def get_active_orders(self, obj: Listing) -> int:
        return obj.orders.filter(
            status__name__in=["requested", "confirmed", "active", "overdue", "unreturned", "disputed"]
        ).count()

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
            "active_orders",
            "created_at",
            "updated_at",
        ]


class ListingCreateSerializer(serializers.ModelSerializer):
    """Serializer for publishing a resource listing (FR6, FR7, CP-401)."""

    title = serializers.CharField(max_length=200, required=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
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

    def to_internal_value(self, data):
        if hasattr(data, "_mutable"):
            was_mutable = data._mutable
            data._mutable = True
            try:
                self._normalize_create_payload(data)
                return super().to_internal_value(data)
            finally:
                data._mutable = was_mutable

        if isinstance(data, dict):
            data = dict(data)
            self._normalize_create_payload(data)

        return super().to_internal_value(data)

    def _normalize_create_payload(self, data: Any) -> None:
        # Category normalization
        if "category_id" in data and "category" not in data:
            data["category"] = data["category_id"]
        elif "category" in data:
            raw_cat = data["category"]
            if isinstance(raw_cat, dict):
                data["category"] = raw_cat.get("id")
            elif isinstance(raw_cat, str) and raw_cat.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_cat)
                    if isinstance(parsed, dict) and "id" in parsed:
                        data["category"] = parsed["id"]
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(raw_cat, str) and not raw_cat.strip().isdigit():
                clean_name = raw_cat.strip()
                cat_obj = ListingCategory.objects.filter(name__iexact=clean_name).first()
                if not cat_obj:
                    cat_obj = ListingCategory.objects.filter(name__icontains=clean_name).first()
                if not cat_obj:
                    cat_obj, _ = ListingCategory.objects.get_or_create(name=clean_name)
                data["category"] = cat_obj.id

        # Pickup location normalization
        if "pickup_location_id" in data and "pickup_location" not in data:
            data["pickup_location"] = data["pickup_location_id"]
        elif "pickup_location" in data:
            raw_loc = data["pickup_location"]
            if isinstance(raw_loc, dict):
                data["pickup_location"] = raw_loc.get("id")
            elif isinstance(raw_loc, str) and raw_loc.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_loc)
                    if isinstance(parsed, dict) and "id" in parsed:
                        data["pickup_location"] = parsed["id"]
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(raw_loc, str) and not raw_loc.strip().isdigit():
                clean_name = raw_loc.strip()
                loc_obj = PickupLocation.objects.filter(name__iexact=clean_name, deleted_at__isnull=True).first()
                if not loc_obj:
                    loc_obj = PickupLocation.objects.filter(name__icontains=clean_name, deleted_at__isnull=True).first()
                if not loc_obj:
                    low = clean_name.lower()
                    if 'cea' in low or 'engineering' in low or 'architecture' in low:
                        loc_obj = PickupLocation.objects.filter(Q(name__icontains='engineering') | Q(name__icontains='architecture'), deleted_at__isnull=True).first()
                if not loc_obj:
                    for kw in ['gate', 'library', 'lagoon', 'gym', 'communication']:
                        if kw in clean_name.lower():
                            loc_obj = PickupLocation.objects.filter(name__icontains=kw, deleted_at__isnull=True).first()
                            if loc_obj:
                                break
                if not loc_obj:
                    loc_obj = PickupLocation.objects.filter(deleted_at__isnull=True).first()
                if loc_obj:
                    data["pickup_location"] = loc_obj.id

        # Ownership confirmation alias and truthy string coercion
        if "ownership_confirmed" in data and "is_ownership_confirmed" not in data:
            data["is_ownership_confirmed"] = data["ownership_confirmed"]
        if "is_ownership_confirmed" in data:
            val = data["is_ownership_confirmed"]
            if isinstance(val, str):
                if val.lower() in ("on", "true", "1", "yes"):
                    data["is_ownership_confirmed"] = True
                elif val.lower() in ("false", "0", "no", ""):
                    data["is_ownership_confirmed"] = False

        # Description default
        if "description" not in data or data.get("description") is None:
            data["description"] = ""

        # Rate per day: clean currency symbols or strings like "₱10"
        if "rate_per_day" in data:
            val = data.get("rate_per_day")
            if val is not None and isinstance(val, str):
                cleaned = re.sub(r"[^\d.]", "", val).strip()
                if not cleaned:
                    if hasattr(data, "setlist"):
                        data.pop("rate_per_day", None)
                    else:
                        data["rate_per_day"] = None
                else:
                    data["rate_per_day"] = cleaned

        # Availability date aliases
        if "available_from" in data and "start_date" not in data:
            data["start_date"] = data["available_from"]
        if "available_to" in data and "end_date" not in data:
            data["end_date"] = data["available_to"]

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
            clean_str = val.strip().split("T")[0]
            try:
                return date.fromisoformat(clean_str)
            except ValueError:
                raise serializers.ValidationError(
                    f"Date '{val}' must be in YYYY-MM-DD format."
                )
        raise serializers.ValidationError("Invalid date value.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        photos = _extract_and_validate_photos(self)
        attrs["photos"] = photos

        # Extract and validate availability windows
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
        elif (
            "start_date" in self.initial_data or "available_from" in self.initial_data
        ):
            start_val = self.initial_data.get("start_date") or self.initial_data.get(
                "available_from"
            )
            end_val = self.initial_data.get("end_date") or self.initial_data.get(
                "available_to"
            )
            if not end_val:
                s_date = self._parse_date(start_val)
                end_val = (s_date + timedelta(days=365)).isoformat()
            windows_data = [
                {
                    "start_date": start_val,
                    "end_date": end_val,
                }
            ]
        elif not windows_data:
            today_d = timezone.now().date()
            windows_data = [
                {
                    "start_date": today_d.isoformat(),
                    "end_date": (today_d + timedelta(days=365)).isoformat(),
                }
            ]

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

            if start_d < today and end_d >= today:
                start_d = today

            if start_d > end_d:
                raise serializers.ValidationError(
                    {
                        "availability_windows": "Start date must be before or equal to end date."
                    }
                )

            if end_d < today:
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
            photos=validated_data.get("photos", []),
            availability_windows=validated_data.get("availability_windows", []),
        )


class ListingUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating resource listing metadata, photos, or availability (CP-402)."""

    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False)
    condition = serializers.CharField(max_length=50, required=False)
    rate_per_day = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=ListingCategory.objects.all(),
        required=False,
    )
    pickup_location = serializers.PrimaryKeyRelatedField(
        queryset=PickupLocation.objects.all(),
        required=False,
    )

    class Meta:
        model = Listing
        fields = [
            "title",
            "description",
            "condition",
            "rate_per_day",
            "category",
            "pickup_location",
        ]

    def to_internal_value(self, data):
        if hasattr(data, "_mutable"):
            was_mutable = data._mutable
            data._mutable = True
            try:
                self._normalize_update_payload(data)
                return super().to_internal_value(data)
            finally:
                data._mutable = was_mutable

        if isinstance(data, dict):
            data = dict(data)
            self._normalize_update_payload(data)

        return super().to_internal_value(data)

    def _normalize_update_payload(self, data: Any) -> None:
        if "category_id" in data and "category" not in data:
            data["category"] = data["category_id"]
        elif "category" in data:
            raw_cat = data["category"]
            if isinstance(raw_cat, dict):
                data["category"] = raw_cat.get("id")
            elif isinstance(raw_cat, str) and raw_cat.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_cat)
                    if isinstance(parsed, dict) and "id" in parsed:
                        data["category"] = parsed["id"]
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(raw_cat, str) and not raw_cat.strip().isdigit():
                clean_name = raw_cat.strip()
                cat_obj = ListingCategory.objects.filter(name__iexact=clean_name).first()
                if not cat_obj:
                    cat_obj = ListingCategory.objects.filter(name__icontains=clean_name).first()
                if not cat_obj:
                    cat_obj, _ = ListingCategory.objects.get_or_create(name=clean_name)
                data["category"] = cat_obj.id

        if "pickup_location_id" in data and "pickup_location" not in data:
            data["pickup_location"] = data["pickup_location_id"]
        elif "pickup_location" in data:
            raw_loc = data["pickup_location"]
            if isinstance(raw_loc, dict):
                data["pickup_location"] = raw_loc.get("id")
            elif isinstance(raw_loc, str) and raw_loc.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_loc)
                    if isinstance(parsed, dict) and "id" in parsed:
                        data["pickup_location"] = parsed["id"]
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(raw_loc, str) and not raw_loc.strip().isdigit():
                clean_name = raw_loc.strip()
                loc_obj = PickupLocation.objects.filter(name__iexact=clean_name, deleted_at__isnull=True).first()
                if not loc_obj:
                    loc_obj = PickupLocation.objects.filter(name__icontains=clean_name, deleted_at__isnull=True).first()
                if not loc_obj:
                    low = clean_name.lower()
                    if 'cea' in low or 'engineering' in low or 'architecture' in low:
                        loc_obj = PickupLocation.objects.filter(Q(name__icontains='engineering') | Q(name__icontains='architecture'), deleted_at__isnull=True).first()
                if not loc_obj:
                    for kw in ['gate', 'library', 'lagoon', 'gym', 'communication']:
                        if kw in clean_name.lower():
                            loc_obj = PickupLocation.objects.filter(name__icontains=kw, deleted_at__isnull=True).first()
                            if loc_obj:
                                break
                if not loc_obj:
                    loc_obj = PickupLocation.objects.filter(deleted_at__isnull=True).first()
                if loc_obj:
                    data["pickup_location"] = loc_obj.id

        if "rate_per_day" in data:
            val = data.get("rate_per_day")
            if val is not None and isinstance(val, str):
                cleaned = re.sub(r"[^\d.]", "", val).strip()
                if not cleaned:
                    if hasattr(data, "setlist"):
                        data.pop("rate_per_day", None)
                    else:
                        data["rate_per_day"] = None
                else:
                    data["rate_per_day"] = cleaned

    def _parse_date(self, val: Any) -> date:
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            clean_str = val.strip().split("T")[0]
            try:
                return date.fromisoformat(clean_str)
            except ValueError:
                raise serializers.ValidationError(
                    f"Date '{val}' must be in YYYY-MM-DD format."
                )
        raise serializers.ValidationError("Invalid date value.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance and self.instance.status.name == LISTING_STATUS_DELETED:
            raise serializers.ValidationError("Cannot edit a deleted listing.")

        pickup_location = attrs.get("pickup_location")
        if pickup_location and pickup_location.deleted_at is not None:
            raise serializers.ValidationError(
                {"pickup_location": "Selected pickup location is not available."}
            )

        photos = _extract_and_validate_photos(self)
        if photos:
            attrs["photos"] = photos

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

        if windows_data:
            today = timezone.now().date()
            parsed_windows = []
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

                parsed_windows.append({"start_date": start_d, "end_date": end_d})
            attrs["availability_windows"] = parsed_windows

        return attrs

    def update(self, instance: Listing, validated_data: dict[str, Any]) -> Listing:
        return update_listing(listing=instance, validated_data=validated_data)
