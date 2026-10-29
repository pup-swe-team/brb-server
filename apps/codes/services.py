"""Business logic and services for handover and return authentication codes (CP-504, CP-505)."""

from __future__ import annotations

import logging
import math
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.core.constants import (
    AUTH_CODE_EXPIRY_HOURS,
    AUTH_CODE_LOCKOUT_MINUTES,
    AUTH_CODE_LOCKOUT_THRESHOLD,
    DEFAULT_AUTH_CODE_EXPIRY_HOURS,
    DEFAULT_AUTH_CODE_LOCKOUT_MINUTES,
    DEFAULT_AUTH_CODE_LOCKOUT_THRESHOLD,
)
from apps.core.selectors import get_int_config
from apps.listings.services import block_dates_for_order, release_dates_for_order
from apps.notifications.constants import (
    NOTIFICATION_TYPE_CODE_GENERATION,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
    NOTIFICATION_TYPE_CONFIRMED_RETURN,
    NOTIFICATION_TYPE_REPORT_UPDATES,
)
from apps.notifications.models import Notification, NotificationType
from apps.orders.constants import (
    FILE_TYPE_PHOTO,
    FILE_TYPE_VIDEO,
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_DISPUTED,
    ORDER_STATUS_RETURNED,
    RETURN_ELIGIBLE_ORDER_STATUSES,
)
from apps.orders.models import Dispute, DisputeEvidence, FileType, Order, OrderStatus
from apps.users.models import User

from .constants import (
    CODE_STATUS_ACTIVE,
    CODE_STATUS_EXPIRED,
    CODE_STATUS_USED,
    CODE_TYPE_HANDOVER,
    CODE_TYPE_RETURN,
)
from .models import AuthCode, AuthCodeAttempt, AuthCodeStatus, AuthCodeType

logger = logging.getLogger(__name__)


class OrderStateConflictError(APIException):
    """Raised when an order's current status does not allow the requested code operation."""

    status_code = 409
    default_detail = "Order status does not allow this operation."
    default_code = "order_state_conflict"


class CodeVerificationLockedError(APIException):
    """Raised when repeated failed code entry attempts trigger a temporary lockout."""

    status_code = 429
    default_detail = (
        "Too many failed code entry attempts. Please wait before trying again."
    )
    default_code = "code_verification_locked"


def auth_code_expiry_hours() -> int:
    """Hours a handover or return code stays valid, Admin-configurable via SystemConfig."""
    hours = get_int_config(AUTH_CODE_EXPIRY_HOURS, DEFAULT_AUTH_CODE_EXPIRY_HOURS)
    return hours if hours > 0 else DEFAULT_AUTH_CODE_EXPIRY_HOURS


def auth_code_lockout_threshold() -> int:
    """Consecutive failed attempts before code entry locks, Admin-configurable."""
    threshold = get_int_config(
        AUTH_CODE_LOCKOUT_THRESHOLD, DEFAULT_AUTH_CODE_LOCKOUT_THRESHOLD
    )
    return threshold if threshold > 0 else DEFAULT_AUTH_CODE_LOCKOUT_THRESHOLD


def auth_code_lockout_minutes() -> int:
    """Minutes a code entry lockout lasts, Admin-configurable."""
    minutes = get_int_config(
        AUTH_CODE_LOCKOUT_MINUTES, DEFAULT_AUTH_CODE_LOCKOUT_MINUTES
    )
    return minutes if minutes > 0 else DEFAULT_AUTH_CODE_LOCKOUT_MINUTES


def _notify_user(*, user_id: int, event_name: str, reference_id: str) -> Notification:
    notification_type, _ = NotificationType.objects.get_or_create(name=event_name)
    return Notification.objects.create(
        user_id=user_id,
        type=notification_type,
        reference_id=reference_id,
    )


def _set_order_status(order: Order, status_name: str) -> Order:
    status_row, _ = OrderStatus.objects.get_or_create(name=status_name)
    order.status = status_row
    order.save(update_fields=["status", "updated_at"])
    return order


def expire_stale_auth_codes(
    *,
    order: Order | None = None,
    code_type_name: str | None = None,
    now: datetime | None = None,
) -> list[int]:
    """
    Flip any 'active' AuthCode whose expires_at <= now to 'expired'.
    Can be scoped to a single order/code_type (check-on-access) or run globally (cron).
    """
    now = now or timezone.now()
    qs = AuthCode.objects.filter(
        auth_status__name=CODE_STATUS_ACTIVE,
        expires_at__lte=now,
    )
    if order is not None:
        qs = qs.filter(order=order)
    if code_type_name is not None:
        qs = qs.filter(code_type__name=code_type_name)

    expired_ids = list(qs.values_list("pk", flat=True))
    if not expired_ids:
        return []

    expired_status, _ = AuthCodeStatus.objects.get_or_create(name=CODE_STATUS_EXPIRED)
    AuthCode.objects.filter(pk__in=expired_ids).update(auth_status=expired_status)
    return expired_ids


def get_code_lockout_until(
    *,
    order: Order,
    code_type_name: str,
    actor: User,
    now: datetime | None = None,
) -> datetime | None:
    """
    Compute whether `actor` is currently locked out from verifying `code_type_name`
    codes on `order` based on `AuthCodeAttempt` history.

    Every streak of `auth_code_lockout_threshold()` consecutive failed attempts
    starts a lockout for `auth_code_lockout_minutes()`. Once that lockout window
    elapses (or a successful attempt occurs), the streak resets so the user gets
    a fresh set of attempts.
    """
    now = now or timezone.now()
    threshold = auth_code_lockout_threshold()
    lockout_delta = timedelta(minutes=auth_code_lockout_minutes())

    attempts = list(
        AuthCodeAttempt.objects.filter(
            code__order=order,
            code__code_type__name=code_type_name,
            attempted_by=actor,
        )
        .order_by("attempted_at", "pk")
        .values_list("was_successful", "attempted_at")
    )

    consecutive_failures = 0
    locked_until: datetime | None = None

    for was_successful, attempted_at in attempts:
        if locked_until is not None and attempted_at >= locked_until:
            locked_until = None
            consecutive_failures = 0

        if was_successful:
            consecutive_failures = 0
            locked_until = None
        else:
            consecutive_failures += 1
            if consecutive_failures >= threshold:
                locked_until = attempted_at + lockout_delta
                consecutive_failures = 0

    if locked_until is not None and locked_until > now:
        return locked_until
    return None


def _enforce_not_locked_out(
    *,
    order: Order,
    code_type_name: str,
    actor: User,
    now: datetime,
) -> None:
    locked_until = get_code_lockout_until(
        order=order,
        code_type_name=code_type_name,
        actor=actor,
        now=now,
    )
    if locked_until is not None:
        minutes_remaining = max(1, math.ceil((locked_until - now).total_seconds() / 60))
        raise CodeVerificationLockedError(
            detail={
                "detail": (
                    f"Code verification is temporarily locked due to repeated failed "
                    f"attempts. Try again in {minutes_remaining} minute(s)."
                ),
                "locked_until": locked_until.isoformat(),
            }
        )


def _generate_unique_6_digit_code(order: Order) -> str:
    """Generate a 6-digit numeric OTP distinct from prior codes on the same order."""
    existing_values = set(
        AuthCode.objects.filter(order=order).values_list("code_value", flat=True)
    )
    for _ in range(20):
        candidate = f"{secrets.randbelow(1_000_000):06d}"
        if candidate not in existing_values:
            return candidate
    return f"{secrets.randbelow(1_000_000):06d}"


def _generate_order_auth_code(
    *,
    order: Order,
    code_type_name: str,
    actor: User,
    notify_user_id: int,
    now: datetime | None = None,
) -> AuthCode:
    """Shared atomic helper to supersede prior active codes, mint a 6-digit OTP, and log/notify."""
    now = now or timezone.now()
    code_type, _ = AuthCodeType.objects.get_or_create(name=code_type_name)
    active_status, _ = AuthCodeStatus.objects.get_or_create(name=CODE_STATUS_ACTIVE)
    expired_status, _ = AuthCodeStatus.objects.get_or_create(name=CODE_STATUS_EXPIRED)

    # Supersede any existing active code of the same type for this order
    AuthCode.objects.filter(
        order=order,
        code_type=code_type,
        auth_status=active_status,
    ).update(auth_status=expired_status)

    code_value = _generate_unique_6_digit_code(order)
    expires_at = now + timedelta(hours=auth_code_expiry_hours())

    auth_code = AuthCode.objects.create(
        order=order,
        code_type=code_type,
        code_value=code_value,
        expires_at=expires_at,
        auth_status=active_status,
    )

    _notify_user(
        user_id=notify_user_id,
        event_name=NOTIFICATION_TYPE_CODE_GENERATION,
        reference_id=str(order.pk),
    )

    logger.info(
        "Generated %s AuthCode #%d for Order #%d by User #%d (expires %s)",
        code_type_name,
        auth_code.pk,
        order.pk,
        actor.pk,
        expires_at.isoformat(),
    )
    return auth_code


def _validate_and_consume_auth_code(
    *,
    order: Order,
    code_type_name: str,
    actor: User,
    code_value: str,
    allowed_order_statuses: tuple[str, ...],
    invalid_state_message: str,
    now: datetime | None = None,
) -> AuthCode:
    """
    Validate a submitted 6-digit OTP against `order` and `code_type_name`.

    Note: Not wrapped in `@transaction.atomic` at the outer level so that failed
    `AuthCodeAttempt` records and lazy expiry updates commit to the database even
    when `ValidationError` is raised.
    """
    now = now or timezone.now()
    cleaned_code = (code_value or "").strip()

    # 1. Check lockout before accepting any code verification attempt
    _enforce_not_locked_out(
        order=order,
        code_type_name=code_type_name,
        actor=actor,
        now=now,
    )

    # 2. Lazily expire any active codes whose 3-hour window has passed
    expire_stale_auth_codes(order=order, code_type_name=code_type_name, now=now)

    codes_qs = (
        AuthCode.objects.filter(order=order, code_type__name=code_type_name)
        .select_related("auth_status", "code_type")
        .order_by("-generated_at", "-pk")
    )
    latest_code = codes_qs.first()

    if latest_code is None:
        if order.status.name not in allowed_order_statuses:
            raise OrderStateConflictError(invalid_state_message)
        raise ValidationError(
            {
                "code": f"No {code_type_name} code has been generated for this order yet."
            },
            code="no_code_generated",
        )

    matched_code = codes_qs.filter(code_value=cleaned_code).first()

    # 3. Check if the code was already used (even if order status already advanced)
    if matched_code is not None and matched_code.auth_status.name == CODE_STATUS_USED:
        AuthCodeAttempt.objects.create(
            code=matched_code,
            attempted_by=actor,
            was_successful=False,
        )
        logger.info(
            "Rejected already-used %s AuthCode #%d on Order #%d by User #%d",
            code_type_name,
            matched_code.pk,
            order.pk,
            actor.pk,
        )
        raise ValidationError(
            {"code": "This authentication code has already been used."},
            code="code_used",
        )

    # 4. Ensure order is in an eligible status for this transition
    if order.status.name not in allowed_order_statuses:
        raise OrderStateConflictError(invalid_state_message)

    # 5. Check if the code matched an expired code
    if (
        matched_code is not None
        and matched_code.auth_status.name == CODE_STATUS_EXPIRED
    ):
        AuthCodeAttempt.objects.create(
            code=matched_code,
            attempted_by=actor,
            was_successful=False,
        )
        logger.info(
            "Rejected expired %s AuthCode #%d on Order #%d by User #%d",
            code_type_name,
            matched_code.pk,
            order.pk,
            actor.pk,
        )
        raise ValidationError(
            {"code": "This authentication code has expired."},
            code="code_expired",
        )

    # 6. Check if the code is incorrect (does not match any active code)
    if matched_code is None or matched_code.auth_status.name != CODE_STATUS_ACTIVE:
        AuthCodeAttempt.objects.create(
            code=latest_code,
            attempted_by=actor,
            was_successful=False,
        )
        logger.info(
            "Rejected incorrect %s code entry on Order #%d (logged against AuthCode #%d) by User #%d",
            code_type_name,
            order.pk,
            latest_code.pk,
            actor.pk,
        )
        raise ValidationError(
            {"code": "Invalid authentication code."},
            code="invalid_code",
        )

    # 7. Valid active code -> mark used and record successful attempt
    used_status, _ = AuthCodeStatus.objects.get_or_create(name=CODE_STATUS_USED)
    matched_code.auth_status = used_status
    matched_code.used_at = now
    matched_code.save(update_fields=["auth_status", "used_at"])

    AuthCodeAttempt.objects.create(
        code=matched_code,
        attempted_by=actor,
        was_successful=True,
    )
    logger.info(
        "Validated %s AuthCode #%d on Order #%d by User #%d",
        code_type_name,
        matched_code.pk,
        order.pk,
        actor.pk,
    )
    return matched_code


# ---------------------------------------------------------------------------
# CP-504 -- Handover Code Generation & Validation
# ---------------------------------------------------------------------------


@transaction.atomic
def generate_handover_code(
    *,
    order_id: int,
    actor: User,
    now: datetime | None = None,
) -> AuthCode:
    """
    Generate a one-time 6-digit handover code for a Confirmed order (CP-504).
    Only the listing's Lender may generate the handover code.
    """
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("listing", "status"),
        pk=order_id,
    )
    if order.listing.lender_id != actor.pk:
        raise PermissionDenied(
            "Only the listing's lender can generate a handover code."
        )
    if order.status.name != ORDER_STATUS_CONFIRMED:
        raise OrderStateConflictError(
            "Handover codes can only be generated for Confirmed orders."
        )

    return _generate_order_auth_code(
        order=order,
        code_type_name=CODE_TYPE_HANDOVER,
        actor=actor,
        notify_user_id=order.borrower_id,
        now=now,
    )


def verify_handover_code(
    *,
    order_id: int,
    actor: User,
    code_value: str,
    now: datetime | None = None,
) -> tuple[Order, AuthCode]:
    """
    Validate a handover code entered by the Borrower (CP-504).
    On success, transitions the order from Confirmed to Active and starts tracking.
    """
    now = now or timezone.now()
    order = get_object_or_404(
        Order.objects.select_related("listing", "status"),
        pk=order_id,
    )
    if order.borrower_id != actor.pk:
        raise PermissionDenied("Only the borrower can enter the handover code.")

    consumed_code = _validate_and_consume_auth_code(
        order=order,
        code_type_name=CODE_TYPE_HANDOVER,
        actor=actor,
        code_value=code_value,
        allowed_order_statuses=(ORDER_STATUS_CONFIRMED,),
        invalid_state_message="Handover codes can only be verified for Confirmed orders.",
        now=now,
    )

    with transaction.atomic():
        locked_order = (
            Order.objects.select_for_update()
            .select_related("listing", "status")
            .get(pk=order.pk)
        )
        _set_order_status(locked_order, ORDER_STATUS_ACTIVE)
        block_dates_for_order(locked_order)
        _notify_user(
            user_id=locked_order.listing.lender_id,
            event_name=NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
            reference_id=str(locked_order.pk),
        )

    consumed_code.refresh_from_db()
    return locked_order, consumed_code


# ---------------------------------------------------------------------------
# CP-505 -- Return Code Generation & Validation
# ---------------------------------------------------------------------------


def _infer_evidence_file_type(uploaded_file) -> FileType:
    """Resolve FileType ('photo' or 'video') from an uploaded evidence file."""
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    filename = (getattr(uploaded_file, "name", "") or "").lower()
    if content_type.startswith("video/") or filename.endswith(
        (".mp4", ".mov", ".avi", ".mkv", ".webm")
    ):
        file_type, _ = FileType.objects.get_or_create(name=FILE_TYPE_VIDEO)
    else:
        file_type, _ = FileType.objects.get_or_create(name=FILE_TYPE_PHOTO)
    return file_type


@transaction.atomic
def generate_return_code(
    *,
    order_id: int,
    actor: User,
    now: datetime | None = None,
) -> AuthCode:
    """
    Generate a one-time 6-digit return code on return initiation (CP-505).
    Only the order's Borrower may generate the return code for an Active or Overdue order.
    """
    order = get_object_or_404(
        Order.objects.select_for_update().select_related("listing", "status"),
        pk=order_id,
    )
    if order.borrower_id != actor.pk:
        raise PermissionDenied("Only the borrower can generate a return code.")
    if order.status.name not in RETURN_ELIGIBLE_ORDER_STATUSES:
        raise OrderStateConflictError(
            "Return codes can only be generated for Active or Overdue orders."
        )

    return _generate_order_auth_code(
        order=order,
        code_type_name=CODE_TYPE_RETURN,
        actor=actor,
        notify_user_id=order.listing.lender_id,
        now=now,
    )


def verify_return_code(
    *,
    order_id: int,
    actor: User,
    code_value: str,
    flagged: bool = False,
    dispute_description: str = "",
    evidence_files: list | None = None,
    now: datetime | None = None,
) -> tuple[Order, AuthCode, Dispute | None]:
    """
    Validate a return code entered by the Lender (CP-505).

    On success:
      1. Sets order to Returned + stops tracking (releases calendar dates & notifies Borrower).
      2. Auto-sets order to Completed (if no flag) or Disputed (if damage/missing flagged,
         creating a Dispute and attaching any uploaded DisputeEvidence files).
    """
    now = now or timezone.now()
    order = get_object_or_404(
        Order.objects.select_related("listing", "status"),
        pk=order_id,
    )
    if order.listing.lender_id != actor.pk:
        raise PermissionDenied("Only the listing's lender can verify the return code.")

    consumed_code = _validate_and_consume_auth_code(
        order=order,
        code_type_name=CODE_TYPE_RETURN,
        actor=actor,
        code_value=code_value,
        allowed_order_statuses=RETURN_ELIGIBLE_ORDER_STATUSES,
        invalid_state_message="Return codes can only be verified for Active or Overdue orders.",
        now=now,
    )

    dispute: Dispute | None = None
    with transaction.atomic():
        locked_order = (
            Order.objects.select_for_update()
            .select_related("listing", "status")
            .get(pk=order.pk)
        )
        # Step 1: Set Returned + stop tracking + release dates + notify Borrower
        _set_order_status(locked_order, ORDER_STATUS_RETURNED)
        release_dates_for_order(locked_order)
        _notify_user(
            user_id=locked_order.borrower_id,
            event_name=NOTIFICATION_TYPE_CONFIRMED_RETURN,
            reference_id=str(locked_order.pk),
        )

        # Step 2: Auto-set Completed (no flag) or Disputed (damage/missing flagged)
        if flagged:
            _set_order_status(locked_order, ORDER_STATUS_DISPUTED)
            cleaned_desc = (dispute_description or "").strip() or (
                "Item flagged for damage or missing parts upon return."
            )
            dispute = Dispute.objects.create(
                order=locked_order,
                raised_by=actor,
                description=cleaned_desc,
                status=Dispute.StatusChoices.OPEN,
            )
            for evidence_file in evidence_files or []:
                DisputeEvidence.objects.create(
                    dispute=dispute,
                    submitted_by=actor,
                    file_reference=evidence_file,
                    file_type=_infer_evidence_file_type(evidence_file),
                )
            _notify_user(
                user_id=locked_order.borrower_id,
                event_name=NOTIFICATION_TYPE_REPORT_UPDATES,
                reference_id=str(locked_order.pk),
            )
        else:
            _set_order_status(locked_order, ORDER_STATUS_COMPLETED)

    consumed_code.refresh_from_db()
    return locked_order, consumed_code, dispute
