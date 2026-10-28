"""Borrow request validation and creation (CP-501)."""

from datetime import date

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.core.selectors import get_int_config
from apps.listings.models import AvailabilityWindow, BlockedDateRange, Listing
from apps.notifications.models import Notification, NotificationType
from apps.users.models import User

from .models import Order, OrderStatus

BORROWING_LIMIT_KEY = "borrowing_limit"
DEFAULT_BORROWING_LIMIT = 3
LIMIT_COUNTED_STATUSES = ("requested", "confirmed", "active")
BOOKED_STATUSES = ("confirmed", "active")


@transaction.atomic
def request_borrow(
    *, borrower: User, listing_id: int, start_date: date, end_date: date
) -> Order:
    """Validate and create a requested order and lender notification atomically."""
    # Keep this lock order stable across requests. The listing lock serializes
    # requests from different borrowers; the borrower lock serializes limit checks.
    borrower = User.objects.select_for_update().get(pk=borrower.pk)
    listing = get_object_or_404(
        Listing.objects.select_for_update().select_related("status"), pk=listing_id
    )

    if listing.lender_id == borrower.pk:
        raise ValidationError({"listing_id": "You cannot request your own listing."})
    if listing.status.name != "active":
        raise ValidationError({"listing_id": "This listing is not active."})
    if not AvailabilityWindow.objects.filter(
        listing=listing, start_date__lte=start_date, end_date__gte=end_date
    ).exists():
        raise ValidationError(
            {"start_date": "The requested dates are outside listing availability."}
        )

    overlap = {"start_date__lte": end_date, "end_date__gte": start_date}
    if (
        Order.objects.filter(
            listing=listing, status__name__in=BOOKED_STATUSES, **overlap
        ).exists()
        or BlockedDateRange.objects.filter(listing=listing, **overlap).exists()
    ):
        raise ValidationError({"start_date": "The requested dates are unavailable."})

    limit = get_int_config(BORROWING_LIMIT_KEY, DEFAULT_BORROWING_LIMIT)
    if limit < 1:
        limit = DEFAULT_BORROWING_LIMIT
    if (
        Order.objects.filter(
            borrower=borrower, status__name__in=LIMIT_COUNTED_STATUSES
        ).count()
        >= limit
    ):
        raise ValidationError({"listing_id": "You have reached your borrowing limit."})

    requested_status, _ = OrderStatus.objects.get_or_create(name="requested")
    order = Order.objects.create(
        listing=listing,
        borrower=borrower,
        start_date=start_date,
        end_date=end_date,
        status=requested_status,
    )
    notification_type, _ = NotificationType.objects.get_or_create(name="new_request")
    Notification.objects.create(
        user_id=listing.lender_id,
        type=notification_type,
        reference_id=str(order.pk),
    )
    return order
