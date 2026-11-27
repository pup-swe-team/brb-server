"""Business logic and services for order lifecycle (CP-501, CP-502, CP-503), overdue sweep, unreturned escalation, and admin controls (CP-506)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.codes.services import _infer_evidence_file_type, expire_stale_auth_codes
from apps.core.constants import (
    DEFAULT_UNRETURNED_ESCALATION_DAYS,
    UNRETURNED_ESCALATION_DAYS,
)
from apps.core.selectors import get_int_config
from apps.listings.models import AvailabilityWindow, BlockedDateRange, Listing
from apps.listings.services import block_dates_for_order, release_dates_for_order
from apps.notifications.constants import (
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_REPORT_UPDATES,
    NOTIFICATION_TYPE_UNRETURNED_STATUS,
)
from apps.notifications.models import Notification, NotificationType
from apps.users.models import User

from .constants import (
    ALL_ORDER_STATUSES,
    CALENDAR_BLOCKING_ORDER_STATUSES,
    CALENDAR_RELEASING_ORDER_STATUSES,
    CLOSING_UNRETURNED_CASE_STATUSES,
    DISPUTE_ELIGIBLE_ORDER_STATUSES,
    FILE_TYPE_PHOTO,
    FILE_TYPE_VIDEO,
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_DISPUTED,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_RETURNED,
    ORDER_STATUS_UNRETURNED,
    UNRETURNED_CASE_STATUS_ESCALATED,
    UNRETURNED_CASE_STATUS_OPEN,
    UNRETURNED_CASE_STATUS_RETURNED,
)
from .models import (
    Dispute,
    DisputeEvidence,
    Order,
    OrderStatus,
    OrderStatusOverride,
    UnreturnedCase,
    UnreturnedCaseStatus,
)

logger = logging.getLogger(__name__)

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


class OrderCaseConflictError(APIException):
    """Raised when an unreturned case or order state does not allow the requested transition."""

    status_code = 409
    default_detail = "Current state does not allow this operation."
    default_code = "order_case_conflict"


def request_expiry_hours() -> int:
    hours = get_int_config(REQUEST_EXPIRY_HOURS_KEY, DEFAULT_REQUEST_EXPIRY_HOURS)
    return hours if hours > 0 else DEFAULT_REQUEST_EXPIRY_HOURS


def unreturned_escalation_days() -> int:
    """Days an order may stay Overdue before escalating to Unreturned (Admin-configurable, CP-506)."""
    days = get_int_config(
        UNRETURNED_ESCALATION_DAYS, DEFAULT_UNRETURNED_ESCALATION_DAYS
    )
    return days if days > 0 else DEFAULT_UNRETURNED_ESCALATION_DAYS


def _notify_borrower(order: Order, event: str) -> None:
    notification_type, _ = NotificationType.objects.get_or_create(name=event)
    Notification.objects.create(
        user_id=order.borrower_id,
        type=notification_type,
        reference_id=str(order.pk),
    )


def _notify_lender(order: Order, event: str) -> None:
    notification_type, _ = NotificationType.objects.get_or_create(name=event)
    Notification.objects.create(
        user_id=order.listing.lender_id,
        type=notification_type,
        reference_id=str(order.pk),
    )


def _notify_both_parties(order: Order, event_name: str) -> None:
    """Create in-app notifications for both Borrower and Lender of `order`."""
    notification_type, _ = NotificationType.objects.get_or_create(name=event_name)
    recipient_ids = {order.borrower_id, order.listing.lender_id}
    for user_id in recipient_ids:
        Notification.objects.create(
            user_id=user_id,
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


def _active_borrowed_orders_count(borrower: User) -> int:
    return Order.objects.filter(
        borrower=borrower,
        status__name__in=LIMIT_COUNTED_STATUSES,
    ).count()


def _is_range_available(*, listing: Listing, start: date, end: date) -> bool:
    return AvailabilityWindow.objects.filter(
        listing=listing,
        start_date__lte=start,
        end_date__gte=end,
    ).exists()


def _has_overlapping_orders(*, listing: Listing, start: date, end: date) -> bool:
    has_orders = Order.objects.filter(
        listing=listing,
        status__name__in=BOOKED_STATUSES,
        start_date__lte=end,
        end_date__gte=start,
    ).exists()
    if has_orders:
        return True
    return BlockedDateRange.objects.filter(
        listing=listing,
        start_date__lte=end,
        end_date__gte=start,
    ).exists()


@transaction.atomic
def request_borrow(
    *, borrower: User, listing_id: int, start_date: date, end_date: date
) -> Order:
    if not borrower.is_authenticated or not borrower.is_active:
        raise PermissionDenied("Authentication required.")
    if borrower.account_status != User.AccountStatusChoices.ACTIVE:
        raise PermissionDenied(
            "Your account is not active and cannot submit borrow requests."
        )
    if getattr(borrower, "is_flag_confirmed", False):
        raise PermissionDenied(
            "Your account has a confirmed moderation flag and cannot submit new borrow requests."
        )
    if not borrower.has_verified_identity():
        raise PermissionDenied("Identity verification required to borrow items.")

    listing = get_object_or_404(
        Listing.objects.select_for_update().select_related("status", "lender"),
        pk=listing_id,
    )
    if listing.lender_id == borrower.pk:
        raise ValidationError(
            {"listing_id": "You cannot borrow your own listing."},
            code="own_listing",
        )
    if listing.status.name != "active":
        raise ValidationError(
            {"listing_id": "This listing is not currently available for borrowing."},
            code="listing_unavailable",
        )

    raw_limit = get_int_config(BORROWING_LIMIT_KEY, DEFAULT_BORROWING_LIMIT)
    borrowing_limit = raw_limit if raw_limit > 0 else DEFAULT_BORROWING_LIMIT
    current_held = _active_borrowed_orders_count(borrower)
    if current_held >= borrowing_limit:
        raise ValidationError(
            {
                "non_field_errors": (
                    f"borrowing limit reached ({current_held}/{borrowing_limit}). "
                    "Return existing items before requesting new ones."
                )
            },
            code="borrowing_limit_reached",
        )

    if listing.max_duration_days is not None:
        requested_days = (end_date - start_date).days + 1
        if requested_days > listing.max_duration_days:
            raise ValidationError(
                {
                    "end_date": (
                        f"Borrowing period ({requested_days} days) exceeds the lender's "
                        f"maximum of {listing.max_duration_days} day(s)."
                    )
                },
                code="max_duration_exceeded",
            )

    if not _is_range_available(listing=listing, start=start_date, end=end_date):
        raise ValidationError(
            {
                "start_date": "Requested dates fall outside the listing's availability windows."
            },
            code="dates_unavailable",
        )

    if _has_overlapping_orders(listing=listing, start=start_date, end=end_date):
        raise ValidationError(
            {
                "start_date": "The requested dates conflict with an existing reservation."
            },
            code="date_conflict",
        )

    requested_status, _ = OrderStatus.objects.get_or_create(name="requested")
    order = Order.objects.create(
        listing=listing,
        borrower=borrower,
        start_date=start_date,
        end_date=end_date,
        status=requested_status,
    )
    _notify_lender(order, "new_request")
    return order


@transaction.atomic
def respond_to_borrow_request(
    *, lender: User, order_id: int, action: str
) -> tuple[Order, str]:
    if action not in ("accept", "decline"):
        raise ValidationError({"action": "Action must be 'accept' or 'decline'."})

    # Order rows are locked in a deterministic sequence to prevent deadlocks:
    # listing first, then the order itself.
    existing = get_object_or_404(Order.objects.only("id", "listing_id"), pk=order_id)
    listing = Listing.objects.select_for_update().get(pk=existing.listing_id)
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("status"), pk=order_id
    )

    if order.listing.lender_id != lender.pk:
        raise PermissionDenied("Only the listing lender can respond to this request.")

    if order.status.name != "requested":
        raise OrderStateConflict()

    deadline = order.created_at + timedelta(hours=request_expiry_hours())
    today = timezone.localdate()
    if timezone.now() >= deadline or order.start_date < today:
        _expire_order(order)
        return order, "expired"

    if action == "decline":
        _set_order_status(order, "declined")
        release_dates_for_order(order)
        _notify_borrower(order, "decline")
        return order, "declined"

    if _has_overlapping_orders(
        listing=listing, start=order.start_date, end=order.end_date
    ):
        _set_order_status(order, "declined")
        release_dates_for_order(order)
        _notify_borrower(order, "decline")
        return order, "declined"

    _set_order_status(order, "confirmed")
    block_dates_for_order(order)
    _notify_borrower(order, "acceptance")
    return order, "confirmed"


def expire_unanswered_requests() -> list[int]:
    cutoff = timezone.now() - timedelta(hours=request_expiry_hours())
    today = timezone.localdate()
    candidate_ids = list(
        Order.objects.filter(
            Q(status__name="requested"),
            Q(created_at__lte=cutoff) | Q(start_date__lt=today),
        ).values_list("id", flat=True)
    )

    expired_ids = []
    for order_id in candidate_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("status")
                .get(pk=order_id)
            )
            if order.status.name != "requested":
                continue
            if order.created_at > cutoff and order.start_date >= today:
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


def _transition_order_to_overdue(order: Order) -> Order:
    """Set an Active order to Overdue and notify both Borrower and Lender."""
    overdue_status, _ = OrderStatus.objects.get_or_create(name=ORDER_STATUS_OVERDUE)
    order.status = overdue_status
    order.save(update_fields=["status", "updated_at"])
    _notify_both_parties(order, NOTIFICATION_TYPE_OVERDUE_STATUS)
    logger.info("CP-506: marked Order #%d as Overdue", order.pk)
    return order


def _transition_order_to_unreturned(order: Order) -> tuple[Order, UnreturnedCase]:
    """
    Escalate an Overdue order to Unreturned after 7 days Overdue (CP-506):
      1. Sets order status to 'unreturned'.
      2. Auto-suspends the Borrower account.
      3. Opens an Admin review UnreturnedCase idempotently.
      4. Notifies both Borrower and Lender.
    """
    unreturned_status, _ = OrderStatus.objects.get_or_create(
        name=ORDER_STATUS_UNRETURNED
    )
    order.status = unreturned_status
    order.save(update_fields=["status", "updated_at"])

    borrower = User.objects.select_for_update().get(pk=order.borrower_id)
    if borrower.account_status != User.AccountStatusChoices.SUSPENDED:
        borrower.account_status = User.AccountStatusChoices.SUSPENDED
        borrower.save(update_fields=["account_status", "updated_at"])

    open_case_status, _ = UnreturnedCaseStatus.objects.get_or_create(
        name=UNRETURNED_CASE_STATUS_OPEN
    )
    unreturned_case, _ = UnreturnedCase.objects.get_or_create(
        order=order,
        defaults={"status": open_case_status},
    )

    _notify_both_parties(order, NOTIFICATION_TYPE_UNRETURNED_STATUS)
    logger.info(
        "CP-506: marked Order #%d as Unreturned, suspended Borrower #%d, opened UnreturnedCase #%d",
        order.pk,
        borrower.pk,
        unreturned_case.pk,
    )
    return order, unreturned_case


def sync_order_time_derived_status(
    order: Order, *, now: datetime | None = None
) -> Order:
    """
    Check-on-access safety net (DECISIONS.md D-01):
    Recomputes Expired / Overdue / Unreturned status for a single order if time thresholds have passed.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)
    escalation_days = unreturned_escalation_days()

    if order.status.name == "requested":
        deadline = order.created_at + timedelta(hours=request_expiry_hours())
        if now >= deadline or order.start_date < today:
            with transaction.atomic():
                order = (
                    Order.objects.select_for_update()
                    .select_related("listing", "status")
                    .get(pk=order.pk)
                )
                if order.status.name == "requested":
                    deadline = order.created_at + timedelta(
                        hours=request_expiry_hours()
                    )
                    if now >= deadline or order.start_date < today:
                        _expire_order(order)
            return order

    if order.status.name == ORDER_STATUS_ACTIVE and order.end_date < today:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("listing", "status")
                .get(pk=order.pk)
            )
            if order.status.name == ORDER_STATUS_ACTIVE and order.end_date < today:
                _transition_order_to_overdue(order)

    if order.status.name == ORDER_STATUS_OVERDUE:
        days_overdue = (today - order.end_date).days
        if days_overdue >= escalation_days:
            with transaction.atomic():
                order = (
                    Order.objects.select_for_update()
                    .select_related("listing", "status")
                    .get(pk=order.pk)
                )
                if order.status.name == ORDER_STATUS_OVERDUE:
                    current_days = (today - order.end_date).days
                    if current_days >= escalation_days:
                        _transition_order_to_unreturned(order)

    return order


def process_overdue_and_unreturned_orders(*, now: datetime | None = None) -> dict:
    """
    Scheduled sweep for CP-506 (and CP-504/505 stale code expiry):
      1. Expires stale active AuthCode rows whose 3-hour window has elapsed.
      2. Transitions Active orders with `end_date < today` to Overdue + notifies both parties.
      3. Transitions Overdue orders >= `unreturned_escalation_days()` (default 7) past due to
         Unreturned + auto-suspends Borrower + opens UnreturnedCase + notifies both parties.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)
    escalation_days = unreturned_escalation_days()
    unreturned_cutoff_date = today - timedelta(days=escalation_days)
    unreturned_cutoff_dt = now - timedelta(days=escalation_days)

    expired_code_ids = expire_stale_auth_codes(now=now)

    # 0. Upcoming due date notifications (active orders ending tomorrow)
    from apps.notifications.services import process_upcoming_due_date_notifications

    upcoming_due_date_notifs = process_upcoming_due_date_notifications(now=now)

    # 1. Active -> Overdue
    active_candidate_ids = list(
        Order.objects.filter(
            status__name=ORDER_STATUS_ACTIVE,
            end_date__lt=today,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    overdue_order_ids: list[int] = []
    for order_id in active_candidate_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("listing", "status")
                .get(pk=order_id)
            )
            if order.status.name != ORDER_STATUS_ACTIVE or order.end_date >= today:
                continue
            _transition_order_to_overdue(order)
            overdue_order_ids.append(order.pk)

    # 2. Overdue -> Unreturned (after 7 days Overdue)
    overdue_candidate_ids = list(
        Order.objects.filter(status__name=ORDER_STATUS_OVERDUE)
        .filter(
            Q(end_date__lte=unreturned_cutoff_date)
            | Q(updated_at__lte=unreturned_cutoff_dt)
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    unreturned_order_ids: list[int] = []
    opened_case_ids: list[int] = []
    for order_id in overdue_candidate_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related("listing", "status")
                .get(pk=order_id)
            )
            if order.status.name != ORDER_STATUS_OVERDUE:
                continue
            if not (
                order.end_date <= unreturned_cutoff_date
                or order.updated_at <= unreturned_cutoff_dt
            ):
                continue
            _, unreturned_case = _transition_order_to_unreturned(order)
            unreturned_order_ids.append(order.pk)
            opened_case_ids.append(unreturned_case.pk)

    return {
        "expired_code_count": len(expired_code_ids),
        "expired_code_ids": expired_code_ids,
        "upcoming_due_date_count": len(upcoming_due_date_notifs),
        "overdue_count": len(overdue_order_ids),
        "overdue_order_ids": overdue_order_ids,
        "unreturned_escalation_days": escalation_days,
        "unreturned_count": len(unreturned_order_ids),
        "unreturned_order_ids": unreturned_order_ids,
        "opened_case_ids": opened_case_ids,
    }


@transaction.atomic
def escalate_unreturned_case(
    *,
    case_id: int,
    admin: User,
    resolution_notes: str = "",
    evidence_files: list | None = None,
) -> UnreturnedCase:
    """
    Admin escalates an UnreturnedCase to PUP OSS or Campus Security (CP-506):
      - Case status transitions to 'escalated'.
      - escalated_at and escalated_by are recorded.
      - Any attached evidence files (PDF, photo, doc) are persisted under DisputeEvidence.
    """
    case = get_object_or_404(
        UnreturnedCase.objects.select_for_update().select_related(
            "order", "order__listing", "status"
        ),
        pk=case_id,
    )

    escalated_status, _ = UnreturnedCaseStatus.objects.get_or_create(
        name=UNRETURNED_CASE_STATUS_ESCALATED
    )
    case.status = escalated_status
    case.escalated_at = timezone.now()
    case.escalated_by = admin
    cleaned_notes = (resolution_notes or "").strip()
    if cleaned_notes:
        case.resolution_notes = cleaned_notes
    case.save(
        update_fields=[
            "status",
            "escalated_at",
            "escalated_by",
            "resolution_notes",
            "updated_at",
        ]
    )

    # Attach any evidence files submitted with the escalation
    if evidence_files:
        dispute, _ = Dispute.objects.get_or_create(
            order=case.order,
            defaults={
                "raised_by": admin,
                "description": f"Escalated unreturned case #{case.pk}",
                "status": Dispute.StatusChoices.ESCALATED,
            },
        )
        for uploaded_file in evidence_files:
            file_type_model = _infer_evidence_file_type(uploaded_file)
            DisputeEvidence.objects.create(
                dispute=dispute,
                submitted_by=admin,
                file_reference=uploaded_file,
                file_type=file_type_model,
            )

    _notify_both_parties(case.order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info("CP-506: Admin #%d escalated UnreturnedCase #%d", admin.pk, case.pk)
    return case


@transaction.atomic
def close_unreturned_case(
    *,
    case_id: int,
    admin: User,
    close_status: str,
    resolution_notes: str = "",
) -> UnreturnedCase:
    """
    Admin closes an UnreturnedCase as 'returned' or 'unresolved' (CP-506):
      - If closed as 'returned': sets order status to 'returned', creates audit record,
        releases blocked calendar dates, and reinstates the borrower account if they have
        no other open/escalated unreturned cases.
      - If closed as 'unresolved': keeps order as 'unreturned' (borrower stays suspended),
        releases blocked calendar dates, and saves resolution_notes.
    """
    normalized_status = (close_status or "").strip().lower()
    if normalized_status not in CLOSING_UNRETURNED_CASE_STATUSES:
        raise ValidationError(
            {"status": "Case closing status must be 'returned' or 'unresolved'."}
        )

    case = get_object_or_404(
        UnreturnedCase.objects.select_for_update().select_related(
            "order", "order__listing", "order__status", "status"
        ),
        pk=case_id,
    )
    if case.status.name in CLOSING_UNRETURNED_CASE_STATUSES:
        raise OrderCaseConflictError("This unreturned case is already closed.")

    target_case_status, _ = UnreturnedCaseStatus.objects.get_or_create(
        name=normalized_status
    )
    cleaned_notes = (resolution_notes or "").strip()
    case.status = target_case_status
    if cleaned_notes:
        case.resolution_notes = cleaned_notes
    case.save(update_fields=["status", "resolution_notes", "updated_at"])

    order = (
        Order.objects.select_for_update().select_related("status").get(pk=case.order_id)
    )
    release_dates_for_order(order)

    if normalized_status == UNRETURNED_CASE_STATUS_RETURNED:
        previous_status_name = order.status.name
        returned_order_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_RETURNED
        )
        order.status = returned_order_status
        order.save(update_fields=["status", "updated_at"])

        OrderStatusOverride.objects.create(
            order=order,
            admin=admin,
            previous_status=previous_status_name,
            new_status=ORDER_STATUS_RETURNED,
            reason=cleaned_notes
            or "Unreturned case closed as Returned by administrator.",
        )

        # Reinstate borrower if no other open/escalated unreturned cases remain
        remaining_open_cases = (
            UnreturnedCase.objects.filter(
                order__borrower_id=order.borrower_id,
                status__name__in=(
                    UNRETURNED_CASE_STATUS_OPEN,
                    UNRETURNED_CASE_STATUS_ESCALATED,
                ),
            )
            .exclude(pk=case.pk)
            .exists()
        )
        if not remaining_open_cases:
            borrower = User.objects.select_for_update().get(pk=order.borrower_id)
            if borrower.account_status == User.AccountStatusChoices.SUSPENDED:
                borrower.account_status = User.AccountStatusChoices.ACTIVE
                borrower.save(update_fields=["account_status", "updated_at"])

    _notify_both_parties(case.order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info(
        "CP-506: Admin #%d closed UnreturnedCase #%d as '%s'",
        admin.pk,
        case.pk,
        normalized_status,
    )
    return case


@transaction.atomic
def override_order_status(
    *,
    order_id: int,
    admin: User,
    new_status: str,
    reason: str,
) -> tuple[Order, OrderStatusOverride]:
    """
    Admin manual order status correction with a recorded reason (CP-506, FR8, FR14).
    Creates an immutable OrderStatusOverride audit entry and syncs listing calendar blocks.
    """
    normalized_status = (new_status or "").strip().lower()
    if normalized_status not in ALL_ORDER_STATUSES:
        raise ValidationError(
            {
                "new_status": (
                    f"Invalid order status '{new_status}'. Must be one of: "
                    f"{', '.join(ALL_ORDER_STATUSES)}."
                )
            }
        )

    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise ValidationError(
            {"reason": "A reason is required for manual status correction."}
        )

    order = get_object_or_404(
        Order.objects.select_for_update().select_related("listing", "status"),
        pk=order_id,
    )
    previous_status_name = order.status.name

    target_status, _ = OrderStatus.objects.get_or_create(name=normalized_status)
    order.status = target_status
    order.save(update_fields=["status", "updated_at"])

    override_record = OrderStatusOverride.objects.create(
        order=order,
        admin=admin,
        previous_status=previous_status_name,
        new_status=normalized_status,
        reason=cleaned_reason,
    )

    if normalized_status in CALENDAR_BLOCKING_ORDER_STATUSES:
        block_dates_for_order(order)
    elif normalized_status in CALENDAR_RELEASING_ORDER_STATUSES:
        release_dates_for_order(order)

    _notify_both_parties(order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info(
        "CP-506: Admin #%d manually overrode Order #%d status from '%s' to '%s' (Override #%d)",
        admin.pk,
        order.pk,
        previous_status_name,
        normalized_status,
        override_record.pk,
    )
    return order, override_record


# ---------------------------------------------------------------------------
# CP-903 -- Damage / Missing-Item Disputes
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_damage_report(
    *,
    actor: User,
    order_id: int,
    description: str,
    evidence_files: list | None = None,
) -> Dispute:
    """
    Document item damage or missing parts on an eligible order (CP-903).

    - Transitions eligible orders (`active`, `overdue`, `returned`) to `disputed`
      and releases blocked listing dates.
    - Creates a new open `Dispute` if none is open; if the borrower posts on an
      existing open dispute raised by the lender, records `borrower_response`
      without overwriting the lender's original `description`.
    - Persists uploaded photo/video `DisputeEvidence` rows and notifies the
      counterparty.
    """
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("listing", "status"),
        pk=order_id,
    )
    if actor.pk not in (order.borrower_id, order.listing.lender_id):
        raise PermissionDenied("Only the order parties can submit a damage report.")

    cleaned_description = (description or "").strip()
    if not cleaned_description:
        raise ValidationError(
            {"description": ["A description of the damage is required."]}
        )

    if order.status.name not in DISPUTE_ELIGIBLE_ORDER_STATUSES:
        raise OrderCaseConflictError(
            f"Cannot submit a damage dispute for an order with status '{order.status.name}'."
        )

    dispute = (
        Dispute.objects.select_for_update()
        .filter(order=order, status=Dispute.StatusChoices.OPEN)
        .order_by("-created_at")
        .first()
    )
    is_borrower_response = (
        dispute is not None
        and actor.pk == order.borrower_id
        and dispute.raised_by_id != actor.pk
    )
    resolved_uploads = [
        (uploaded_file, _infer_evidence_file_type(uploaded_file))
        for uploaded_file in (evidence_files or [])
    ]
    if not is_borrower_response:
        existing_types = (
            set(dispute.evidences.values_list("file_type__name", flat=True))
            if dispute is not None
            else set()
        )
        combined_types = existing_types | {ft.name for _, ft in resolved_uploads}
        missing: list[str] = []
        if FILE_TYPE_PHOTO not in combined_types:
            missing.append("At least one photo is required.")
        if FILE_TYPE_VIDEO not in combined_types:
            missing.append("At least one video is required.")
        if missing:
            raise ValidationError({"evidence": missing})

    if order.status.name != ORDER_STATUS_DISPUTED:
        _set_order_status(order, ORDER_STATUS_DISPUTED)
        release_dates_for_order(order)

    if dispute is None:
        dispute = Dispute.objects.create(
            order=order,
            raised_by=actor,
            description=cleaned_description,
            status=Dispute.StatusChoices.OPEN,
        )
    elif is_borrower_response:
        dispute.borrower_response = cleaned_description
        dispute.save(update_fields=["borrower_response", "updated_at"])
    else:
        dispute.description = cleaned_description
        dispute.save(update_fields=["description", "updated_at"])

    for uploaded_file, file_type_model in resolved_uploads:
        DisputeEvidence.objects.create(
            dispute=dispute,
            submitted_by=actor,
            file_reference=uploaded_file,
            file_type=file_type_model,
        )

    if actor.pk == order.borrower_id:
        _notify_lender(order, NOTIFICATION_TYPE_REPORT_UPDATES)
    else:
        _notify_borrower(order, NOTIFICATION_TYPE_REPORT_UPDATES)

    logger.info(
        "CP-903: User #%d updated/opened Dispute #%d on Order #%d",
        actor.pk,
        dispute.pk,
        order.pk,
    )
    return dispute


@transaction.atomic
def resolve_dispute(
    *,
    dispute_id: int,
    admin: User,
    resolution_notes: str = "",
) -> Dispute:
    """
    Admin resolves a damage/missing-item dispute to Completed (CP-903, FR14):
      - Rejects already-resolved disputes with 409 Conflict.
      - Sets dispute status to 'resolved', records `resolved_by` and `resolution_notes`.
      - Transitions the order to 'completed' (stamping `completed_at`), releases
        calendar dates, records an immutable `OrderStatusOverride`, and notifies
        both Borrower and Lender.
    """
    dispute = get_object_or_404(
        Dispute.objects.select_for_update().select_related(
            "order", "order__listing", "order__status"
        ),
        pk=dispute_id,
    )
    if dispute.status == Dispute.StatusChoices.RESOLVED:
        raise OrderCaseConflictError("This dispute has already been resolved.")

    cleaned_notes = (resolution_notes or "").strip() or "Resolved by admin"
    dispute.status = Dispute.StatusChoices.RESOLVED
    dispute.resolved_by = admin
    dispute.resolution_notes = cleaned_notes
    dispute.save(
        update_fields=["status", "resolved_by", "resolution_notes", "updated_at"]
    )

    order = (
        Order.objects.select_for_update()
        .select_related("listing", "status")
        .get(pk=dispute.order_id)
    )
    previous_status_name = order.status.name
    completed_status, _ = OrderStatus.objects.get_or_create(name=ORDER_STATUS_COMPLETED)
    order.status = completed_status
    order.save(update_fields=["status", "updated_at"])
    release_dates_for_order(order)

    OrderStatusOverride.objects.create(
        order=order,
        admin=admin,
        previous_status=previous_status_name,
        new_status=ORDER_STATUS_COMPLETED,
        reason=cleaned_notes,
    )

    _notify_both_parties(order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info(
        "CP-903: Admin #%d resolved Dispute #%d on Order #%d -> completed",
        admin.pk,
        dispute.pk,
        order.pk,
    )
    return dispute


@transaction.atomic
def escalate_dispute(
    *,
    dispute_id: int,
    admin: User,
    resolution_notes: str = "",
    evidence_files: list | None = None,
) -> Dispute:
    """
    Admin escalates a damage/missing-item dispute to PUP OSS / Campus Security (CP-903):
      - Rejects already-resolved disputes with 409 Conflict.
      - Sets dispute status to 'escalated', records `resolved_by` (escalating admin)
        and `resolution_notes`, keeps order in 'disputed' status (never 'completed').
      - Persists any optional escalation evidence files and notifies both parties.
    """
    dispute = get_object_or_404(
        Dispute.objects.select_for_update().select_related(
            "order", "order__listing", "order__status"
        ),
        pk=dispute_id,
    )
    if dispute.status == Dispute.StatusChoices.RESOLVED:
        raise OrderCaseConflictError("Cannot escalate an already resolved dispute.")

    cleaned_notes = (
        resolution_notes or ""
    ).strip() or "Escalated to PUP OSS for administrative review"
    dispute.status = Dispute.StatusChoices.ESCALATED
    dispute.resolved_by = admin
    dispute.resolution_notes = cleaned_notes
    dispute.save(
        update_fields=["status", "resolved_by", "resolution_notes", "updated_at"]
    )

    order = (
        Order.objects.select_for_update()
        .select_related("listing", "status")
        .get(pk=dispute.order_id)
    )
    if order.status.name != ORDER_STATUS_DISPUTED:
        _set_order_status(order, ORDER_STATUS_DISPUTED)

    for uploaded_file in evidence_files or []:
        file_type_model = _infer_evidence_file_type(uploaded_file)
        DisputeEvidence.objects.create(
            dispute=dispute,
            submitted_by=admin,
            file_reference=uploaded_file,
            file_type=file_type_model,
        )

    _notify_both_parties(order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info(
        "CP-903: Admin #%d escalated Dispute #%d on Order #%d to PUP OSS",
        admin.pk,
        dispute.pk,
        order.pk,
    )
    return dispute
