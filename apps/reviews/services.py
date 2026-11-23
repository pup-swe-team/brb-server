"""Business logic services for mutual reviews and ratings (CP-601, CP-1102)."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.constants import DEFAULT_REVIEW_WINDOW_DAYS, REVIEW_WINDOW_DAYS
from apps.core.selectors import get_int_config
from apps.orders.constants import ORDER_STATUS_COMPLETED
from apps.orders.models import Order
from apps.users.models import User

from .models import Review
from .selectors import get_user_rating_stats


def review_window_days() -> int:
    """Return the configured post-completion review window in days (default 7)."""
    days = get_int_config(REVIEW_WINDOW_DAYS, DEFAULT_REVIEW_WINDOW_DAYS)
    return days if days > 0 else DEFAULT_REVIEW_WINDOW_DAYS


def get_order_review_deadline(order: Order) -> datetime | None:
    """Return the deadline timestamp for submitting a review on a completed order."""
    if order.status.name != ORDER_STATUS_COMPLETED:
        return None
    completion_time = order.completed_at or order.updated_at
    if completion_time is None:
        return None
    return completion_time + timedelta(days=review_window_days())


def can_user_review_order(
    *,
    order: Order,
    user: User,
    now: datetime | None = None,
) -> bool:
    """Check whether `user` is currently eligible to submit a review on `order`."""
    if not user or not user.is_authenticated:
        return False
    if user.pk not in (order.borrower_id, order.listing.lender_id):
        return False
    if order.status.name != ORDER_STATUS_COMPLETED:
        return False

    deadline = get_order_review_deadline(order)
    current_time = now or timezone.now()
    if deadline is not None and current_time > deadline:
        return False

    return not Review.objects.filter(order_id=order.pk, reviewer_id=user.pk).exists()


@transaction.atomic
def submit_review(
    *,
    order_id: int,
    reviewer: User,
    rating: int,
    comment: str | None = None,
    now: datetime | None = None,
) -> Review:
    """
    Create a 1-to-5 star review for the counterparty of a completed order (CP-601).

    Enforces:
    - Reviewer must be the order's borrower or lender.
    - Order must be in the 'completed' status.
    - Submission must occur within the 7-day post-completion review window.
    - Only one review per party per order is allowed.
    - Immediately recalculates the reviewed user's average rating and review count.
    """
    order = get_object_or_404(
        Order.objects.select_for_update().select_related(
            "listing",
            "listing__lender",
            "borrower",
            "status",
        ),
        pk=order_id,
    )

    if reviewer.pk not in (order.borrower_id, order.listing.lender_id):
        raise PermissionDenied(
            "Only the borrower or lender of this order may submit a review."
        )

    if order.status.name != ORDER_STATUS_COMPLETED:
        raise ValidationError(
            {"detail": "Reviews can only be submitted after the order is completed."},
            code="order_not_completed",
        )

    if Review.objects.filter(order=order, reviewer=reviewer).exists():
        raise ValidationError(
            {"detail": "You have already submitted a review for this order."},
            code="duplicate_review",
        )

    current_time = now or timezone.now()
    window_days = review_window_days()
    completion_time = order.completed_at or order.updated_at
    if completion_time is not None and current_time > completion_time + timedelta(
        days=window_days
    ):
        raise ValidationError(
            {
                "detail": (
                    f"The {window_days}-day review submission window for this order "
                    "has expired."
                )
            },
            code="review_window_expired",
        )

    if rating < 1 or rating > 5:
        raise ValidationError(
            {"rating": "Rating must be an integer between 1 and 5."},
            code="invalid_rating",
        )

    cleaned_comment = comment.strip() if isinstance(comment, str) else None
    try:
        review = Review.objects.create(
            order=order,
            reviewer=reviewer,
            rating=rating,
            comment=cleaned_comment if cleaned_comment else None,
        )
    except IntegrityError as exc:
        raise ValidationError(
            {"detail": "You have already submitted a review for this order."},
            code="duplicate_review",
        ) from exc

    reviewee = review.reviewee
    stats = get_user_rating_stats(reviewee)
    reviewee.average_rating = stats["average_rating"]
    reviewee.review_count = stats["review_count"]
    review._reviewee_stats = stats
    return review


@transaction.atomic
def admin_remove_review(*, review_id: int) -> None:
    """Soft-delete a review without removing its order or report links (CP-1102)."""
    review = get_object_or_404(Review.objects.select_for_update(), pk=review_id)
    if review.deleted_at is None:
        review.deleted_at = timezone.now()
        review.save(update_fields=["deleted_at"])
