"""Database query selectors for the reviews domain (CP-601)."""

from __future__ import annotations

from typing import Any

from django.db.models import Avg, Count, Q, QuerySet

from apps.orders.models import Order
from apps.users.models import User

from .models import Review


def get_user_rating_stats(user: User | int) -> dict[str, Any]:
    """
    Calculate aggregate rating statistics across all non-deleted reviews
    received by `user` (whether acting as Lender or Borrower).
    """
    user_id = user.pk if isinstance(user, User) else int(user)
    reviews_qs = Review.objects.filter(
        Q(order__listing__lender_id=user_id) | Q(order__borrower_id=user_id),
        deleted_at__isnull=True,
    ).exclude(reviewer_id=user_id)

    stats = reviews_qs.aggregate(
        avg_rating=Avg("rating"),
        review_count=Count("id"),
    )

    avg = stats.get("avg_rating")
    return {
        "average_rating": round(float(avg), 2) if avg is not None else None,
        "review_count": stats.get("review_count") or 0,
    }


def get_order_reviews(order: Order | int) -> QuerySet[Review]:
    """Retrieve all non-deleted reviews for an order, newest first."""
    order_id = order.pk if isinstance(order, Order) else int(order)
    return (
        Review.objects.filter(
            order_id=order_id,
            deleted_at__isnull=True,
        )
        .select_related(
            "reviewer",
            "order",
            "order__listing",
            "order__listing__lender",
            "order__borrower",
        )
        .order_by("-created_at")
    )


def get_user_received_reviews(user_id: int) -> QuerySet[Review]:
    """Retrieve all non-deleted reviews received by a user, newest first."""
    return (
        Review.objects.filter(
            Q(order__listing__lender_id=user_id) | Q(order__borrower_id=user_id),
            deleted_at__isnull=True,
        )
        .exclude(reviewer_id=user_id)
        .select_related(
            "reviewer",
            "order",
            "order__listing",
            "order__listing__lender",
            "order__borrower",
        )
        .order_by("-created_at")
    )
