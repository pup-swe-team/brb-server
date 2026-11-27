"""Business logic services for reporting and automatic user flagging (CP-901, CP-902)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.chat.models import Message
from apps.core.constants import (
    AUTO_FLAG_REPORT_THRESHOLD,
    AUTO_FLAG_WINDOW_DAYS,
    DEFAULT_AUTO_FLAG_REPORT_THRESHOLD,
    DEFAULT_AUTO_FLAG_WINDOW_DAYS,
)
from apps.core.selectors import get_int_config
from apps.listings.constants import LISTING_STATUS_DELETED
from apps.listings.models import Listing
from apps.notifications.constants import NOTIFICATION_TYPE_REPORT_UPDATES
from apps.notifications.models import Notification, NotificationType
from apps.orders.models import Order
from apps.reviews.models import Review
from apps.users.models import User

from .constants import (
    DEFAULT_LISTING_REPORT_CATEGORIES,
    DEFAULT_MESSAGE_REPORT_CATEGORIES,
    DEFAULT_REVIEW_REPORT_CATEGORIES,
    DEFAULT_USER_REPORT_CATEGORIES,
    REPORT_STATUS_OPEN,
    REPORT_STATUS_RESOLVED,
    REPORT_TARGET_LISTING,
    REPORT_TARGET_MESSAGE,
    REPORT_TARGET_REVIEW,
    REPORT_TARGET_USER,
)
from .models import (
    ListingReport,
    ListingReportCategory,
    MessageReport,
    MessageReportCategory,
    ReviewReport,
    ReviewReportCategory,
    UserReport,
    UserReportCategory,
)


def _normalize_category_slug(raw: str) -> str:
    slug = raw.strip().lower()
    slug = re.sub(r"[\s/\-]+", "_", slug)
    return re.sub(r"_+", "_", slug).strip("_")


def _resolve_category(
    category_model: type[Any],
    category_input: int | str,
    default_names: tuple[str, ...],
) -> Any:
    if isinstance(category_input, int) or (
        isinstance(category_input, str) and category_input.strip().isdigit()
    ):
        cat_id = int(str(category_input).strip())
        obj = category_model.objects.filter(pk=cat_id).first()
        if obj is not None:
            return obj
        raise ValidationError(
            {"category": f"Report category with id {cat_id} does not exist."},
            code="invalid_category",
        )

    raw_name = str(category_input or "").strip()
    if not raw_name:
        raise ValidationError(
            {"category": "A report category is required."},
            code="invalid_category",
        )

    existing = category_model.objects.filter(name__iexact=raw_name).first()
    if existing is not None:
        return existing

    slug = _normalize_category_slug(raw_name)
    existing_slug = category_model.objects.filter(name__iexact=slug).first()
    if existing_slug is not None:
        return existing_slug

    if slug in default_names:
        obj, _ = category_model.objects.get_or_create(name=slug)
        return obj

    if slug in ("other", "general", "misc", "miscellaneous"):
        obj, _ = category_model.objects.get_or_create(name="other")
        return obj

    # Support friendly frontend category names across user, listing, review, message
    if "spam" in slug:
        if "spam" in default_names:
            obj, _ = category_model.objects.get_or_create(name="spam")
            return obj
        for candidate in ("misleading_description", "irrelevant_review", "other"):
            if candidate in default_names:
                obj, _ = category_model.objects.get_or_create(name=candidate)
                return obj
        obj, _ = category_model.objects.get_or_create(name="spam")
        return obj

    if "fraud" in slug or "scam" in slug:
        for candidate in ("scam_fraud", "misleading_description", "fraud"):
            if candidate in default_names:
                obj, _ = category_model.objects.get_or_create(name=candidate)
                return obj
        obj, _ = category_model.objects.get_or_create(name="scam_fraud")
        return obj

    if "inappropriate" in slug or "offensive" in slug:
        for candidate in (
            "inappropriate_content",
            "inappropriate_pfp",
            "offensive_content",
        ):
            if candidate in default_names:
                obj, _ = category_model.objects.get_or_create(name=candidate)
                return obj

    if "prohibited" in slug and "prohibited" in default_names:
        obj, _ = category_model.objects.get_or_create(name="prohibited")
        return obj

    if "fake" in slug:
        for candidate in ("fake_review", "fake_account", "counterfeit"):
            if candidate in default_names:
                obj, _ = category_model.objects.get_or_create(name=candidate)
                return obj

    raise ValidationError(
        {
            "category": (
                f"Invalid report category '{raw_name}'. Allowed categories: "
                f"{', '.join(default_names)}."
            )
        },
        code="invalid_category",
    )


def _validate_description(description: str | None) -> str:
    cleaned = (description or "").strip()
    if not cleaned:
        raise ValidationError(
            {
                "description": "A non-empty description is required when submitting a report."
            },
            code="blank_description",
        )
    return cleaned


@transaction.atomic
def submit_user_report(
    *,
    reporter: User,
    target_user_id: int,
    category: int | str,
    description: str,
    order_id: int | None = None,
) -> UserReport:
    """
    Submit an open report against a user profile or order counterparty (CP-901).
    Enforces one report per order/interaction server-side.
    """
    target_user = get_object_or_404(User, pk=target_user_id)
    if target_user.pk == reporter.pk:
        raise ValidationError(
            {"detail": "You cannot submit a report against yourself."},
            code="self_report",
        )

    cleaned_description = _validate_description(description)
    category_obj = _resolve_category(
        UserReportCategory,
        category,
        DEFAULT_USER_REPORT_CATEGORIES,
    )

    order: Order | None = None
    if order_id is not None:
        order = get_object_or_404(
            Order.objects.select_related("listing"),
            pk=order_id,
        )
        participants = {order.borrower_id, order.listing.lender_id}
        if {reporter.pk, target_user.pk} != participants:
            raise ValidationError(
                {
                    "order_id": (
                        "Both the reporter and the reported user must be the "
                        "counterparties of the specified order."
                    )
                },
                code="invalid_order_participants",
            )
        if UserReport.objects.filter(
            reporter=reporter,
            target_user=target_user,
            order=order,
        ).exists():
            raise ValidationError(
                {
                    "detail": "You have already submitted a report for this order interaction."
                },
                code="duplicate_report",
            )
    else:
        if UserReport.objects.filter(
            reporter=reporter,
            target_user=target_user,
            order__isnull=True,
        ).exists():
            raise ValidationError(
                {
                    "detail": "You have already submitted a report for this user interaction."
                },
                code="duplicate_report",
            )

    try:
        report = UserReport.objects.create(
            reporter=reporter,
            target_user=target_user,
            category=category_obj,
            order=order,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
        check_and_apply_user_autoflag(user_id=target_user.pk)
        return report
    except IntegrityError as exc:
        raise ValidationError(
            {
                "detail": "You have already submitted a report for this order interaction."
            },
            code="duplicate_report",
        ) from exc


@transaction.atomic
def submit_listing_report(
    *,
    reporter: User,
    target_listing_id: int,
    category: int | str,
    description: str,
) -> ListingReport:
    """
    Submit an open report against a listing (CP-901).
    Enforces one report per (reporter, target_listing) server-side.
    """
    listing = get_object_or_404(
        Listing.objects.select_related("status"),
        pk=target_listing_id,
    )
    if listing.status.name == LISTING_STATUS_DELETED:
        raise Http404("Listing not found.")

    if listing.lender_id == reporter.pk:
        raise ValidationError(
            {"detail": "You cannot report your own listing."},
            code="self_report",
        )

    cleaned_description = _validate_description(description)
    category_obj = _resolve_category(
        ListingReportCategory,
        category,
        DEFAULT_LISTING_REPORT_CATEGORIES,
    )

    if ListingReport.objects.filter(
        reporter=reporter,
        target_listing=listing,
    ).exists():
        raise ValidationError(
            {"detail": "You have already submitted a report for this listing."},
            code="duplicate_report",
        )

    try:
        report = ListingReport.objects.create(
            reporter=reporter,
            target_listing=listing,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
        check_and_apply_user_autoflag(user_id=listing.lender_id)
        return report
    except IntegrityError as exc:
        raise ValidationError(
            {"detail": "You have already submitted a report for this listing."},
            code="duplicate_report",
        ) from exc


@transaction.atomic
def submit_review_report(
    *,
    reporter: User,
    target_review_id: int,
    category: int | str,
    description: str,
) -> ReviewReport:
    """
    Submit an open report against a review (CP-901, ties to CP-601).
    Enforces one report per (reporter, target_review) server-side.
    """
    review = get_object_or_404(
        Review,
        pk=target_review_id,
        deleted_at__isnull=True,
    )
    if review.reviewer_id == reporter.pk:
        raise ValidationError(
            {"detail": "You cannot report your own review."},
            code="self_report",
        )

    cleaned_description = _validate_description(description)
    category_obj = _resolve_category(
        ReviewReportCategory,
        category,
        DEFAULT_REVIEW_REPORT_CATEGORIES,
    )

    if ReviewReport.objects.filter(
        reporter=reporter,
        target_review=review,
    ).exists():
        raise ValidationError(
            {"detail": "You have already submitted a report for this review."},
            code="duplicate_report",
        )

    try:
        report = ReviewReport.objects.create(
            reporter=reporter,
            target_review=review,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
        check_and_apply_user_autoflag(user_id=review.reviewer_id)
        return report
    except IntegrityError as exc:
        raise ValidationError(
            {"detail": "You have already submitted a report for this review."},
            code="duplicate_report",
        ) from exc


@transaction.atomic
def submit_message_report(
    *,
    reporter: User,
    target_message_id: int,
    category: int | str,
    description: str,
) -> MessageReport:
    """
    Submit an open report against a chat message (CP-901).
    Enforces conversation participation (404 for outsiders) and one report per message.
    """
    message = get_object_or_404(
        Message.objects.select_related("conversation"),
        pk=target_message_id,
    )
    conversation = message.conversation
    if reporter.pk not in (conversation.user_a_id, conversation.user_b_id):
        raise Http404("Message not found.")

    if message.sender_id == reporter.pk:
        raise ValidationError(
            {"detail": "You cannot report your own message."},
            code="self_report",
        )

    cleaned_description = _validate_description(description)
    category_obj = _resolve_category(
        MessageReportCategory,
        category,
        DEFAULT_MESSAGE_REPORT_CATEGORIES,
    )

    if MessageReport.objects.filter(
        reporter=reporter,
        target_message=message,
    ).exists():
        raise ValidationError(
            {"detail": "You have already submitted a report for this message."},
            code="duplicate_report",
        )

    try:
        report = MessageReport.objects.create(
            reporter=reporter,
            target_message=message,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
        check_and_apply_user_autoflag(user_id=message.sender_id)
        return report
    except IntegrityError as exc:
        raise ValidationError(
            {"detail": "You have already submitted a report for this message."},
            code="duplicate_report",
        ) from exc


def submit_report(
    *,
    reporter: User,
    target_type: str,
    target_id: int,
    category: int | str,
    description: str,
    order_id: int | None = None,
) -> UserReport | ListingReport | ReviewReport | MessageReport:
    """Unified dispatcher for submitting any of the four report types (CP-901)."""
    normalized_type = (target_type or "").strip().lower()
    if normalized_type == REPORT_TARGET_USER:
        return submit_user_report(
            reporter=reporter,
            target_user_id=target_id,
            category=category,
            description=description,
            order_id=order_id,
        )
    if normalized_type == REPORT_TARGET_LISTING:
        return submit_listing_report(
            reporter=reporter,
            target_listing_id=target_id,
            category=category,
            description=description,
        )
    if normalized_type == REPORT_TARGET_REVIEW:
        return submit_review_report(
            reporter=reporter,
            target_review_id=target_id,
            category=category,
            description=description,
        )
    if normalized_type == REPORT_TARGET_MESSAGE:
        return submit_message_report(
            reporter=reporter,
            target_message_id=target_id,
            category=category,
            description=description,
        )
    raise ValidationError(
        {
            "target_type": (
                f"Invalid target_type '{target_type}'. Must be one of: "
                "user, listing, review, message."
            )
        },
        code="invalid_target_type",
    )


def auto_flag_report_threshold() -> int:
    """Minimum number of reports in the rolling window to trigger automatic flagging (default 3)."""
    val = get_int_config(AUTO_FLAG_REPORT_THRESHOLD, DEFAULT_AUTO_FLAG_REPORT_THRESHOLD)
    return val if val > 0 else DEFAULT_AUTO_FLAG_REPORT_THRESHOLD


def auto_flag_window_days() -> int:
    """Rolling window in days for counting repeated reports against a user (default 30)."""
    val = get_int_config(AUTO_FLAG_WINDOW_DAYS, DEFAULT_AUTO_FLAG_WINDOW_DAYS)
    return val if val > 0 else DEFAULT_AUTO_FLAG_WINDOW_DAYS


def get_user_rolling_report_count(
    *,
    user_id: int,
    now: datetime | None = None,
    window_days: int | None = None,
) -> int:
    """Count total reports targeting a user or their content within the rolling window."""
    current_time = now or timezone.now()
    days = window_days if window_days is not None else auto_flag_window_days()
    cutoff = current_time - timedelta(days=days)

    user_reports = UserReport.objects.filter(
        target_user_id=user_id,
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).count()
    listing_reports = ListingReport.objects.filter(
        target_listing__lender_id=user_id,
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).count()
    review_reports = ReviewReport.objects.filter(
        target_review__reviewer_id=user_id,
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).count()
    message_reports = MessageReport.objects.filter(
        target_message__sender_id=user_id,
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).count()

    return user_reports + listing_reports + review_reports + message_reports


def check_and_apply_user_autoflag(
    *,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    """
    Check if a specific user reaches the rolling 30-day report threshold (CP-902).
    If threshold is met and user is not flagged, immediately auto-flag them (check-on-write).
    Returns True if user was newly flagged, False otherwise.
    """
    threshold = auto_flag_report_threshold()
    total_reports = get_user_rolling_report_count(user_id=user_id, now=now)
    if total_reports >= threshold:
        current_time = now or timezone.now()
        with transaction.atomic():
            user = (
                User.objects.select_for_update()
                .filter(pk=user_id, is_staff=False, is_superuser=False)
                .exclude(account_status=User.AccountStatusChoices.BANNED)
                .first()
            )
            if user and not user.is_flagged:
                user.is_flagged = True
                user.flagged_at = current_time
                user.save(update_fields=["is_flagged", "flagged_at", "updated_at"])
                return True
    return False


@transaction.atomic
def auto_flag_repeatedly_reported_users(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Sweep reports in the rolling 30-day window and flag users with 3+ reports (CP-902).

    Leaves flagged accounts completely unrestricted (`account_status='active'` and
    `is_flag_confirmed=False`) until an Administrator explicitly confirms the flag.
    """
    current_time = now or timezone.now()
    threshold = auto_flag_report_threshold()
    window_days = auto_flag_window_days()
    cutoff = current_time - timedelta(days=window_days)

    counts: Counter[int] = Counter()

    for target_uid in UserReport.objects.filter(
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).values_list("target_user_id", flat=True):
        counts[int(target_uid)] += 1

    for lender_uid in ListingReport.objects.filter(
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).values_list("target_listing__lender_id", flat=True):
        counts[int(lender_uid)] += 1

    for reviewer_uid in ReviewReport.objects.filter(
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).values_list("target_review__reviewer_id", flat=True):
        counts[int(reviewer_uid)] += 1

    for sender_uid in MessageReport.objects.filter(
        created_at__gte=cutoff,
        created_at__lte=current_time,
    ).values_list("target_message__sender_id", flat=True):
        counts[int(sender_uid)] += 1

    qualifying_user_ids = [uid for uid, total in counts.items() if total >= threshold]

    newly_flagged_ids: list[int] = []
    if qualifying_user_ids:
        candidates = (
            User.objects.select_for_update()
            .filter(
                pk__in=qualifying_user_ids,
                is_staff=False,
                is_superuser=False,
            )
            .exclude(account_status=User.AccountStatusChoices.BANNED)
            .order_by("pk")
        )
        for user in candidates:
            if not user.is_flagged:
                user.is_flagged = True
                user.flagged_at = current_time
                user.save(update_fields=["is_flagged", "flagged_at", "updated_at"])
                newly_flagged_ids.append(user.pk)

    return {
        "flagged_count": len(newly_flagged_ids),
        "flagged_user_ids": newly_flagged_ids,
        "qualifying_user_ids": sorted(qualifying_user_ids),
        "threshold": threshold,
        "window_days": window_days,
        "executed_at": current_time.isoformat(),
    }


# ---------------------------------------------------------------------------
# CP-1103 -- Admin Report Queue Listing & Resolution Persistence
# ---------------------------------------------------------------------------


class ReportStateConflictError(APIException):
    """Raised when an Admin attempts to resolve an already-resolved report."""

    status_code = 409
    default_detail = "This report has already been resolved."
    default_code = "report_state_conflict"


REPORT_MODEL_BY_TYPE: dict[str, type[Any]] = {
    REPORT_TARGET_USER: UserReport,
    REPORT_TARGET_LISTING: ListingReport,
    REPORT_TARGET_REVIEW: ReviewReport,
    REPORT_TARGET_MESSAGE: MessageReport,
}


def _normalize_report_row(
    report: UserReport | ListingReport | ReviewReport | MessageReport,
    report_type: str,
) -> dict[str, Any]:
    if isinstance(report, UserReport):
        target_id = report.target_user_id
        target_display = report.target_user.full_name or report.target_user.email
        subject_user_id = report.target_user_id
        subject_user_name = target_display
    elif isinstance(report, ListingReport):
        target_id = report.target_listing_id
        target_display = report.target_listing.title
        subject_user_id = report.target_listing.lender_id
        subject_user_name = (
            report.target_listing.lender.full_name or report.target_listing.lender.email
        )
    elif isinstance(report, ReviewReport):
        target_id = report.target_review_id
        target_display = f"Review #{report.target_review_id}"
        subject_user_id = report.target_review.reviewer_id
        subject_user_name = (
            report.target_review.reviewer.full_name
            or report.target_review.reviewer.email
        )
    else:
        target_id = report.target_message_id
        snippet = (
            report.target_message.content[:60] + "..."
            if len(report.target_message.content) > 60
            else report.target_message.content
        )
        target_display = snippet
        subject_user_id = report.target_message.sender_id
        subject_user_name = (
            report.target_message.sender.full_name or report.target_message.sender.email
        )

    return {
        "id": report.pk,
        "report_type": report_type,
        "reporter_id": report.reporter_id,
        "reporter_name": report.reporter.full_name or report.reporter.email,
        "target_id": target_id,
        "target_display": target_display,
        "subject_user_id": subject_user_id,
        "subject_user_name": subject_user_name,
        "category": report.category.name if report.category else "",
        "description": report.description,
        "status": report.status,
        "resolved_by_id": report.resolved_by_id,
        "resolved_by_name": (
            report.resolved_by.full_name if report.resolved_by else None
        ),
        "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
        "resolution_notes": report.resolution_notes or "",
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "_sort_ts": report.created_at,
    }


def list_reports(
    *,
    report_type: str = "all",
    status_filter: str = REPORT_STATUS_OPEN,
    limit_per_type: int = 100,
) -> list[dict[str, Any]]:
    """Return normalized Admin report queue items across the four report models (CP-1103)."""
    normalized_type = (report_type or "all").strip().lower()
    normalized_status = (status_filter or REPORT_STATUS_OPEN).strip().lower()

    types_to_query = (
        (
            REPORT_TARGET_USER,
            REPORT_TARGET_LISTING,
            REPORT_TARGET_REVIEW,
            REPORT_TARGET_MESSAGE,
        )
        if normalized_type == "all"
        else (normalized_type,)
    )

    items: list[dict[str, Any]] = []
    for rtype in types_to_query:
        if rtype == REPORT_TARGET_USER:
            qs = UserReport.objects.select_related(
                "reporter", "target_user", "category", "resolved_by"
            )
        elif rtype == REPORT_TARGET_LISTING:
            qs = ListingReport.objects.select_related(
                "reporter",
                "target_listing",
                "target_listing__lender",
                "category",
                "resolved_by",
            )
        elif rtype == REPORT_TARGET_REVIEW:
            qs = ReviewReport.objects.select_related(
                "reporter",
                "target_review",
                "target_review__reviewer",
                "category",
                "resolved_by",
            )
        elif rtype == REPORT_TARGET_MESSAGE:
            qs = MessageReport.objects.select_related(
                "reporter",
                "target_message",
                "target_message__sender",
                "category",
                "resolved_by",
            )
        else:
            raise ValidationError(
                {
                    "type": (
                        f"Invalid report type '{report_type}'. Must be one of: "
                        "all, user, listing, review, message."
                    )
                }
            )

        if normalized_status != "all":
            qs = qs.filter(status=normalized_status)

        for row in qs.order_by("-created_at", "-pk")[:limit_per_type]:
            items.append(_normalize_report_row(row, rtype))

    items.sort(key=lambda entry: entry["_sort_ts"], reverse=True)
    for entry in items:
        entry.pop("_sort_ts", None)
    return items


@transaction.atomic
def resolve_report(
    *,
    report_type: str,
    report_id: int,
    admin: User,
    resolution_notes: str = "",
) -> UserReport | ListingReport | ReviewReport | MessageReport:
    """
    Persist Admin resolution of a report across any of the 4 report tables (CP-1103, FR14).

    - Locks the report row and rejects double-resolution with 409 Conflict.
    - Records `status='resolved'`, `resolved_by`, `resolved_at`, and `resolution_notes`.
    - Sends an in-app `report_updates` notification to the reporter.
    """
    normalized_type = (report_type or "").strip().lower()
    model = REPORT_MODEL_BY_TYPE.get(normalized_type)
    if model is None:
        raise ValidationError(
            {
                "report_type": (
                    f"Invalid report type '{report_type}'. Must be one of: "
                    "user, listing, review, message."
                )
            }
        )

    report = get_object_or_404(model.objects.select_for_update(), pk=report_id)
    if report.status == REPORT_STATUS_RESOLVED:
        raise ReportStateConflictError()

    cleaned_notes = (resolution_notes or "").strip()
    report.status = REPORT_STATUS_RESOLVED
    report.resolved_by = admin
    report.resolved_at = timezone.now()
    report.resolution_notes = cleaned_notes
    report.save(
        update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "resolution_notes",
        ]
    )

    notification_type, _ = NotificationType.objects.get_or_create(
        name=NOTIFICATION_TYPE_REPORT_UPDATES
    )
    Notification.objects.create(
        user_id=report.reporter_id,
        type=notification_type,
        reference_id=str(report.pk),
    )
    return report
