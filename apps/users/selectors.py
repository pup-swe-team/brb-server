from django.db.models import Avg, Count, Q, QuerySet

from apps.reviews.models import Review

from .models import User


def search_lenders(q: str | None = None) -> QuerySet[User]:
    """
    Search for active, verified lenders by name (CP-302).

    Exclusion rules:
    - Only users with lender_status='active' (excludes 'none', 'revoked')
    - Only users with account_status='active' (excludes 'suspended', 'banned', 'deactivated')
    - Annotates active_listing_count without N+1 queries.
    """
    qs = User.objects.filter(
        account_status=User.AccountStatusChoices.ACTIVE,
        lender_status=User.LenderStatusChoices.ACTIVE,
    ).annotate(
        active_listing_count=Count(
            "listings",
            filter=Q(listings__status__name="active"),
            distinct=True,
        )
    )

    if q:
        cleaned_q = q.strip()
        if cleaned_q:
            qs = qs.filter(full_name__icontains=cleaned_q)

    return qs.order_by("full_name")


def get_lender_profile(user_id: int) -> User | None:
    """
    Fetch a verified lender by ID for public profile viewing (CP-304).

    Returns the User instance with average rating, review count, and
    preloaded active listings, or None if the lender does not exist,
    is suspended/banned/deactivated, or is not an active lender.
    """
    try:
        lender = User.objects.get(
            pk=user_id,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
    except User.DoesNotExist:
        return None

    # Reviews where this lender was the reviewee (written by borrowers on lender's listings)
    reviews_qs = Review.objects.filter(
        order__listing__lender=lender,
        deleted_at__isnull=True,
    ).exclude(reviewer=lender)

    stats = reviews_qs.aggregate(
        avg_rating=Avg("rating"),
        review_count=Count("id"),
    )

    avg = stats["avg_rating"]
    lender.average_rating = round(avg, 1) if avg is not None else None
    lender.review_count = stats["review_count"] or 0

    lender.prefetched_active_listings = list(
        lender.listings.filter(status__name="active")
        .select_related("category", "pickup_location", "status")
        .prefetch_related("photos")
        .order_by("-created_at")
    )

    return lender
