"""Borrow request creation and lender response services (CP-501, CP-502)."""

from datetime import date, timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.core.selectors import get_int_config
from apps.listings.models import AvailabilityWindow, BlockedDateRange, Listing
from apps.listings.services import block_dates_for_order, release_dates_for_order
from apps.notifications.models import Notification, NotificationType
from apps.users.models import User

from .models import Order, OrderStatus

BORROWING_LIMIT_KEY = "borrowing_limit"
DEFAULT_BORROWING_LIMIT = 3
LIMIT_COUNTED_STATUSES = ("requested", "confirmed", "active")
BOOKED_STATUSES = ("confirmed", "active")
REQUEST_EXPIRY_HOURS_KEY = "borrow_request_expiry_hours"
DEFAULT_REQUEST_EXPIRY_HOURS = 48


class OrderStateConflict(APIException):
    status_code = 409
    default_detail = "This borrow request is no longer awaiting a response."
    default_code = "order_state_conflict"


def request_expiry_hours() -> int:
    hours = get_int_config(REQUEST_EXPIRY_HOURS_KEY, DEFAULT_REQUEST_EXPIRY_HOURS)
    return hours if hours > 0 else DEFAULT_REQUEST_EXPIRY_HOURS


def _notify_borrower(order: Order, event: str) -> None:
    notification_type, _ = NotificationType.objects.get_or_create(name=event)
    Notification.objects.create(
        user_id=order.borrower_id,
        type=notification_type,
        reference_id=str(order.pk),
    )


def _set_order_status(order: Order, status_name: str) -> None:
    status_row, _ = OrderStatus.objects.get_or_create(name=status_name)
    order.status = status_row
    order.save(update_fields=["status", "updated_at"])


def _expire_order(order: Order) -> None:
    _set_order_status(order, "expired")
    release_dates_for_order(order)
    _notify_borrower(order, "expiry")


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


@transaction.atomic
def respond_to_borrow_request(
    *, lender: User, order_id: int, action: str
) -> tuple[Order, str]:
    """Return the updated order and outcome: accepted, declined, or expired."""
    if action not in ("accept", "decline"):
        raise ValueError(f"Unsupported borrow request action: {action}")

    # Lock the listing before the order, matching CP-501's listing lock. This
    # serializes competing acceptances for overlapping requested orders.
    existing = get_object_or_404(Order.objects.only("id", "listing_id"), pk=order_id)
    listing = Listing.objects.select_for_update().get(pk=existing.listing_id)
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("status"), pk=order_id
    )
    if listing.lender_id != lender.pk:
        raise PermissionDenied("Only the listing's lender can respond to this request.")
    if order.status.name != "requested":
        raise OrderStateConflict()

    if order.created_at <= timezone.now() - timedelta(hours=request_expiry_hours()):
        _expire_order(order)
        return order, "expired"

    if action == "decline":
        _set_order_status(order, "declined")
        release_dates_for_order(order)
        _notify_borrower(order, "decline")
        return order, "declined"

    overlap = {"start_date__lte": order.end_date, "end_date__gte": order.start_date}
    conflicting_order = Order.objects.filter(
        listing=listing, status__name__in=BOOKED_STATUSES, **overlap
    ).exclude(pk=order.pk)
    conflicting_block = BlockedDateRange.objects.filter(
        listing=listing, **overlap
    ).exclude(order_id=order.pk)
    if conflicting_order.exists() or conflicting_block.exists():
        _set_order_status(order, "declined")
        release_dates_for_order(order)
        _notify_borrower(order, "decline")
        return order, "declined"

    _set_order_status(order, "confirmed")
    block_dates_for_order(order)
    _notify_borrower(order, "acceptance")
    return order, "accepted"


def expire_unanswered_requests(*, now=None) -> list[int]:
    """Expire overdue Requested orders; recheck each under a row lock."""
    now = now or timezone.now()
    cutoff = now - timedelta(hours=request_expiry_hours())
    candidate_ids = list(
        Order.objects.filter(status__name="requested", created_at__lte=cutoff)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    expired_ids = []
    for order_id in candidate_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("status")
                .get(pk=order_id)
            )
            if order.status.name != "requested" or order.created_at > cutoff:
                continue
            _expire_order(order)
            expired_ids.append(order.pk)
    return expired_ids


@transaction.atomic
def cancel_order(*, actor: User, order_id: int, reason: str) -> Order:
    """Cancel a Requested or Confirmed order and notify its other party."""
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise ValidationError({"reason": "A cancellation reason is required."})

    # Match the lock order used by lender acceptance, so a competing response
    # cannot confirm an order after cancellation has released its dates.
    existing = get_object_or_404(Order.objects.only("id", "listing_id"), pk=order_id)
    listing = Listing.objects.select_for_update().get(pk=existing.listing_id)
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("status"), pk=order_id
    )
    if actor.pk not in (order.borrower_id, listing.lender_id):
        raise PermissionDenied("Only the borrower or lender can cancel this order.")
    if order.status.name not in ("requested", "confirmed"):
        raise OrderStateConflict("Only Requested or Confirmed orders can be cancelled.")

    cancelled_status, _ = OrderStatus.objects.get_or_create(name="cancelled")
    order.status = cancelled_status
    order.cancel_reason = cleaned_reason
    order.save(update_fields=["status", "cancel_reason", "updated_at"])
    release_dates_for_order(order)

    recipient_id = (
        listing.lender_id if actor.pk == order.borrower_id else order.borrower_id
    )
    notification_type, _ = NotificationType.objects.get_or_create(name="cancellation")
    Notification.objects.create(
        user_id=recipient_id,
        type=notification_type,
        reference_id=str(order.pk),
    )
    return order
