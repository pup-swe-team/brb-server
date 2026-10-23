"""Database query selectors for the listings domain (CP-301, CP-303)."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, F, Q, QuerySet

from apps.reviews.models import Review
from apps.users.models import User

from .models import BlockedDateRange, Listing


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


def search_listings(
    *,
    q: str | None = None,
    category: int | None = None,
    condition: str | None = None,
    pickup_location: int | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    free_only: bool = False,
    available_from: date | None = None,
    available_to: date | None = None,
    sort: str | None = None,
) -> QuerySet[Listing]:
    """
    Search and filter listings for browse and search screens (CP-301).

    Enforces mandatory exclusions:
    - Excludes deactivated, deleted, or non-active listings
    - Excludes listings from suspended, banned, or inactive user accounts
    - Excludes listings from revoked lenders
    """
    qs = (
        Listing.objects.filter(
            status__name="active",
            lender__account_status=User.AccountStatusChoices.ACTIVE,
            lender__lender_status=User.LenderStatusChoices.ACTIVE,
        )
        .select_related(
            "lender",
            "category",
            "pickup_location",
            "status",
        )
        .prefetch_related(
            "photos",
        )
    )

    if q:
        cleaned_q = q.strip()
        if cleaned_q:
            qs = qs.filter(
                Q(title__icontains=cleaned_q) | Q(description__icontains=cleaned_q)
            )

    if category is not None:
        qs = qs.filter(category_id=category)

    if condition:
        cleaned_condition = condition.strip()
        if cleaned_condition:
            qs = qs.filter(condition__iexact=cleaned_condition)

    if pickup_location is not None:
        qs = qs.filter(pickup_location_id=pickup_location)

    if min_price is not None:
        qs = qs.filter(rate_per_day__gte=min_price)

    if max_price is not None:
        qs = qs.filter(rate_per_day__lte=max_price)

    if free_only:
        qs = qs.filter(Q(rate_per_day__isnull=True) | Q(rate_per_day=0))

    if available_from and available_to:
        blocked_listing_ids = BlockedDateRange.objects.filter(
            start_date__lte=available_to,
            end_date__gte=available_from,
        ).values_list("listing_id", flat=True)
        qs = qs.exclude(id__in=blocked_listing_ids)
    elif available_from:
        blocked_listing_ids = BlockedDateRange.objects.filter(
            start_date__lte=available_from,
            end_date__gte=available_from,
        ).values_list("listing_id", flat=True)
        qs = qs.exclude(id__in=blocked_listing_ids)
    elif available_to:
        blocked_listing_ids = BlockedDateRange.objects.filter(
            start_date__lte=available_to,
            end_date__gte=available_to,
        ).values_list("listing_id", flat=True)
        qs = qs.exclude(id__in=blocked_listing_ids)

    allowed_sorts = {
        "created_at": "created_at",
        "-created_at": "-created_at",
        "rate_per_day": "rate_per_day",
        "-rate_per_day": "-rate_per_day",
        "title": "title",
        "-title": "-title",
    }
    sort_field = allowed_sorts.get(sort, "-created_at")
    return qs.order_by(sort_field)
