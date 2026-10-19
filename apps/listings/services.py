from datetime import date

from django.db import transaction
from django.db.models import QuerySet

from apps.orders.models import Order

from .models import BlockedDateRange, Listing


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
