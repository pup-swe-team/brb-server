"""Business logic and services for order overdue detection, unreturned escalation, and admin controls (CP-506)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.codes.services import _infer_evidence_file_type, expire_stale_auth_codes
from apps.core.constants import (
    DEFAULT_UNRETURNED_ESCALATION_DAYS,
    UNRETURNED_ESCALATION_DAYS,
)
from apps.core.selectors import get_int_config
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
    ORDER_STATUS_ACTIVE,
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


class OrderCaseConflictError(APIException):
    """Raised when an unreturned case or order state does not allow the requested transition."""

    status_code = 409
    default_detail = "Current state does not allow this operation."
    default_code = "order_case_conflict"


def unreturned_escalation_days() -> int:
    """Days an order may stay Overdue before escalating to Unreturned (Admin-configurable, CP-506)."""
    days = get_int_config(
        UNRETURNED_ESCALATION_DAYS, DEFAULT_UNRETURNED_ESCALATION_DAYS
    )
    return days if days > 0 else DEFAULT_UNRETURNED_ESCALATION_DAYS


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
    Recomputes Overdue / Unreturned status for a single order if time thresholds have passed.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)
    escalation_days = unreturned_escalation_days()
    unreturned_cutoff_date = today - timedelta(days=escalation_days)
    unreturned_cutoff_dt = now - timedelta(days=escalation_days)

    with transaction.atomic():
        locked = (
            Order.objects.select_for_update()
            .select_related("listing", "status")
            .get(pk=order.pk)
        )
        if locked.status.name == ORDER_STATUS_ACTIVE and locked.end_date < today:
            _transition_order_to_overdue(locked)

        if locked.status.name == ORDER_STATUS_OVERDUE and (
            locked.end_date <= unreturned_cutoff_date
            or locked.updated_at <= unreturned_cutoff_dt
        ):
            _transition_order_to_unreturned(locked)

        return locked


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
    now: datetime | None = None,
) -> UnreturnedCase:
    """
    Admin escalates an UnreturnedCase to PUP OSS / Campus Security with optional
    attached evidence files and notes (CP-506).
    """
    now = now or timezone.now()
    case = get_object_or_404(
        UnreturnedCase.objects.select_for_update().select_related(
            "order", "order__listing", "order__status", "status"
        ),
        pk=case_id,
    )
    if case.status.name in CLOSING_UNRETURNED_CASE_STATUSES:
        raise OrderCaseConflictError(
            "Cannot escalate an unreturned case that has already been closed."
        )

    escalated_status, _ = UnreturnedCaseStatus.objects.get_or_create(
        name=UNRETURNED_CASE_STATUS_ESCALATED
    )
    cleaned_notes = (resolution_notes or "").strip()
    case.status = escalated_status
    case.escalated_at = now
    case.escalated_by = admin
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

    if evidence_files:
        dispute = (
            Dispute.objects.filter(order=case.order).order_by("-created_at").first()
        )
        if dispute is None:
            dispute = Dispute.objects.create(
                order=case.order,
                raised_by=admin,
                description=cleaned_notes
                or "Escalated to PUP OSS / Campus Security for unreturned item.",
                status=Dispute.StatusChoices.ESCALATED,
            )
        elif dispute.status != Dispute.StatusChoices.ESCALATED:
            dispute.status = Dispute.StatusChoices.ESCALATED
            dispute.save(update_fields=["status", "updated_at"])

        for evidence_file in evidence_files:
            DisputeEvidence.objects.create(
                dispute=dispute,
                submitted_by=admin,
                file_reference=evidence_file,
                file_type=_infer_evidence_file_type(evidence_file),
            )

    _notify_both_parties(case.order, NOTIFICATION_TYPE_REPORT_UPDATES)
    logger.info(
        "CP-506: Admin #%d escalated UnreturnedCase #%d (Order #%d) to OSS/Campus Security",
        admin.pk,
        case.pk,
        case.order_id,
    )
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
    Admin closes an UnreturnedCase as 'returned' or 'unresolved' (CP-506).

    - If closed as 'returned': updates the order status to 'returned', records an
      OrderStatusOverride audit entry, releases blocked calendar dates, and reinstates
      the borrower if they have no other open/escalated unreturned cases.
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
