"""Business logic and services for the listings domain (CP-401)."""

from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.users.models import User

from .constants import (
    DELETION_BLOCKING_ORDER_STATUSES,
    LISTING_STATUS_ACTIVE,
    LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_DELETED,
)
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


@transaction.atomic
def deactivate_listing(*, listing: Listing) -> Listing:
    """Soft-remove a listing from search by transitioning its status to 'deactivated' (CP-402)."""
    if listing.status.name == LISTING_STATUS_DELETED:
        raise ValidationError("Cannot deactivate a deleted listing.")

    deactivated_status, _ = ListingStatus.objects.get_or_create(
        name=LISTING_STATUS_DEACTIVATED
    )
    listing.status = deactivated_status
    listing.save(update_fields=["status", "updated_at"])
    return listing


@transaction.atomic
def reactivate_listing(*, listing: Listing) -> Listing:
    """Restore a deactivated listing back to 'active' status (CP-402)."""
    if listing.status.name == LISTING_STATUS_DELETED:
        raise ValidationError("Cannot reactivate a deleted listing.")

    active_status, _ = ListingStatus.objects.get_or_create(name=LISTING_STATUS_ACTIVE)
    listing.status = active_status
    listing.save(update_fields=["status", "updated_at"])
    return listing


@transaction.atomic
def delete_listing(*, listing: Listing) -> None:
    """
    Perform a soft delete on a listing, changing its status to 'deleted' (CP-402).
    Blocks deletion if the listing has any ongoing orders (confirmed, active, overdue, unreturned, disputed).
    """
    blocking_orders = listing.orders.filter(
        status__name__in=DELETION_BLOCKING_ORDER_STATUSES
    )
    if blocking_orders.exists():
        blocking_names = ", ".join(
            sorted(set(blocking_orders.values_list("status__name", flat=True)))
        )
        raise ValidationError(
            f"Cannot delete a listing with ongoing orders ({blocking_names})."
        )

    deleted_status, _ = ListingStatus.objects.get_or_create(name=LISTING_STATUS_DELETED)
    listing.status = deleted_status
    listing.save(update_fields=["status", "updated_at"])


@transaction.atomic
def update_listing(
    *,
    listing: Listing,
    validated_data: dict[str, Any],
) -> Listing:
    """Update listing details, photos, or availability windows (CP-402)."""
    if listing.status.name == LISTING_STATUS_DELETED:
        raise ValidationError("Cannot edit a deleted listing.")

    photos = validated_data.pop("photos", None)
    availability_windows = validated_data.pop("availability_windows", None)

    for attr, value in validated_data.items():
        setattr(listing, attr, value)
    listing.save()

    if photos is not None:
        listing.photos.all().delete()
        for photo_file in photos:
            ListingPhoto.objects.create(
                listing=listing,
                file_reference=photo_file,
            )

    if availability_windows is not None:
        listing.availability_windows.all().delete()
        for window in availability_windows:
            AvailabilityWindow.objects.create(
                listing=listing,
                start_date=window["start_date"],
                end_date=window["end_date"],
            )

    return listing
