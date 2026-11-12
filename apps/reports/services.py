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
from rest_framework.exceptions import ValidationError

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
from apps.orders.models import Order
from apps.reviews.models import Review
from apps.users.models import User

from .constants import (
    DEFAULT_LISTING_REPORT_CATEGORIES,
    DEFAULT_MESSAGE_REPORT_CATEGORIES,
    DEFAULT_REVIEW_REPORT_CATEGORIES,
    DEFAULT_USER_REPORT_CATEGORIES,
    REPORT_STATUS_OPEN,
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
    if "fraud" in slug or "scam" in slug:
        for candidate in ("scam_fraud", "misleading_description", "fraud"):
            if candidate in default_names:
                obj, _ = category_model.objects.get_or_create(name=candidate)
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
        return UserReport.objects.create(
            reporter=reporter,
            target_user=target_user,
            category=category_obj,
            order=order,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
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
        return ListingReport.objects.create(
            reporter=reporter,
            target_listing=listing,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
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
        return ReviewReport.objects.create(
            reporter=reporter,
            target_review=review,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
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
        return MessageReport.objects.create(
            reporter=reporter,
            target_message=message,
            category=category_obj,
            description=cleaned_description,
            status=REPORT_STATUS_OPEN,
        )
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
