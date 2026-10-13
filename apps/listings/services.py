"""Business logic and services for the listings domain (CP-401)."""

from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.users.models import User

from .constants import LISTING_STATUS_ACTIVE
from .models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)


@transaction.atomic
def create_listing(
    *,
    lender: User,
    title: str,
    description: str,
    category: ListingCategory,
    condition: str,
    pickup_location: PickupLocation,
    rate_per_day: Decimal | None,
    is_ownership_confirmed: bool,
    photos: list[UploadedFile],
    availability_windows: list[dict[str, Any]],
    status: ListingStatus | None = None,
) -> Listing:
    """Create a new resource listing along with photos and availability calendar windows."""
    if status is None:
        status, _ = ListingStatus.objects.get_or_create(name=LISTING_STATUS_ACTIVE)

    listing = Listing.objects.create(
        lender=lender,
        title=title,
        description=description,
        category=category,
        condition=condition,
        pickup_location=pickup_location,
        rate_per_day=rate_per_day,
        is_ownership_confirmed=is_ownership_confirmed,
        status=status,
    )

    for photo_file in photos:
        ListingPhoto.objects.create(
            listing=listing,
            file_reference=photo_file,
        )

    for window in availability_windows:
        AvailabilityWindow.objects.create(
            listing=listing,
            start_date=window["start_date"],
            end_date=window["end_date"],
        )

    return listing
