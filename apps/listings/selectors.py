"""Database query selectors for the listings domain (CP-303)."""

from typing import Any

from django.db.models import Avg, Count, F, QuerySet

from apps.listings.models import Listing
from apps.reviews.models import Review
from apps.users.models import User


def get_lender_rating_stats(lender: User) -> dict[str, Any]:
    """
    Calculate aggregate rating statistics across all completed orders
    for listings owned by this lender where the borrower reviewed the transaction.
    """
    stats = Review.objects.filter(
        order__listing__lender=lender,
        reviewer=F("order__borrower"),
        deleted_at__isnull=True,
    ).aggregate(
        avg_rating=Avg("rating"),
        total_reviews=Count("id"),
    )

    avg = stats.get("avg_rating")
    return {
        "rating_average": round(float(avg), 2) if avg is not None else None,
        "total_reviews": stats.get("total_reviews", 0),
    }


def get_listing_reviews(listing: Listing) -> QuerySet[Review]:
    """
    Retrieve all non-deleted reviews submitted by borrowers for completed orders
    associated with this specific listing, ordered newest to oldest.
    """
    return (
        Review.objects.filter(
            order__listing=listing,
            reviewer=F("order__borrower"),
            deleted_at__isnull=True,
        )
        .select_related("reviewer")
        .order_by("-created_at")
    )
