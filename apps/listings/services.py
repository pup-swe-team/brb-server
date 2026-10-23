"""Business logic and services for the listings domain (CP-401, CP-402, CP-403)."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError

from apps.orders.models import Order
from apps.users.models import User

from .constants import (
    DELETION_BLOCKING_ORDER_STATUSES,
    LISTING_STATUS_ACTIVE,
    LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_DELETED,
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


@transaction.atomic
def block_dates_for_order(order: Order) -> BlockedDateRange:
    """
    Block dates on a listing's availability calendar for a confirmed order (CP-403).

    Ensures that once an order is confirmed, the corresponding dates
    cannot be double-booked by other borrowers. Idempotent: if a blocked range
    already exists for this order, its dates are synchronized and returned.
    """
    if order.start_date > order.end_date:
        raise ValueError(
            f"Invalid order date range: start_date ({order.start_date}) "
            f"cannot be after end_date ({order.end_date})."
        )

    blocked_range, created = BlockedDateRange.objects.get_or_create(
        order=order,
        defaults={
            "listing": order.listing,
            "start_date": order.start_date,
            "end_date": order.end_date,
            "reason": f"Order #{order.pk} confirmed",
        },
    )

    if not created:
        # If order dates or listing changed, synchronize them
        updated = False
        if blocked_range.listing_id != order.listing_id:
            blocked_range.listing = order.listing
            updated = True
        if blocked_range.start_date != order.start_date:
            blocked_range.start_date = order.start_date
            updated = True
        if blocked_range.end_date != order.end_date:
            blocked_range.end_date = order.end_date
            updated = True
        if updated:
            blocked_range.save()

    return blocked_range


@transaction.atomic
def release_dates_for_order(order: Order) -> int:
    """
    Release blocked calendar dates when an order is cancelled, declined, or completed (CP-403).

    Idempotent: returns the count of deleted blocked ranges (0 if already released).
    """
    deleted_count, _ = BlockedDateRange.objects.filter(order=order).delete()
    return deleted_count


def is_listing_available_for_range(
    listing: Listing,
    start_date: date,
    end_date: date,
    exclude_order_id: int | None = None,
) -> bool:
    """
    Check if a listing is free of conflicting blocked dates for the specified range [start_date, end_date].

    Returns True if available (no overlap with any blocked date ranges), False otherwise.
    Two date ranges [A_start, A_end] and [B_start, B_end] overlap when:
    A_start <= B_end AND A_end >= B_start.
    """
    if start_date > end_date:
        raise ValueError(
            f"Invalid query date range: start_date ({start_date}) "
            f"cannot be after end_date ({end_date})."
        )

    qs = BlockedDateRange.objects.filter(
        listing=listing,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )

    if exclude_order_id is not None:
        qs = qs.exclude(order_id=exclude_order_id)

    return not qs.exists()


def get_blocked_dates_for_listing(listing: Listing) -> QuerySet[BlockedDateRange]:
    """
    Retrieve all blocked date ranges for a listing, ordered by start_date ascending.
    """
    return listing.blocked_dates.order_by("start_date")
