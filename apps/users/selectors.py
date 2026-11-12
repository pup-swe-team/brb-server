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


def search_admin_users(
    *,
    q: str | None = None,
    account_status: str | None = None,
    affiliation: str | None = None,
    lender_status: str | None = None,
    flagged: str | None = None,
) -> QuerySet[User]:
    """
    Search and filter users for administrative and moderation views (CP-1101, CP-1109, CP-902).

    Supports filtering by:
    - `q`: keyword search matching email, full_name, contact_number, or identity document ID number
    - `account_status`: 'active', 'suspended', 'pending_review', 'banned', 'deactivated'
    - `affiliation`: 'Student', 'Faculty', 'Staff'
    - `lender_status`: 'none', 'active', 'revoked'
    - `flagged`: 'true', 'false', 'confirmed', 'unconfirmed'
    """
    qs = User.objects.all().select_related("municipality", "province")

    if q:
        cleaned_q = q.strip()
        if cleaned_q:
            qs = qs.filter(
                Q(email__icontains=cleaned_q)
                | Q(full_name__icontains=cleaned_q)
                | Q(contact_number__icontains=cleaned_q)
                | Q(identity_documents__id_number__icontains=cleaned_q)
            ).distinct()

    if account_status and account_status != "all":
        qs = qs.filter(account_status=account_status)

    if affiliation and affiliation != "all":
        qs = qs.filter(affiliation=affiliation)

    if lender_status and lender_status != "all":
        qs = qs.filter(lender_status=lender_status)

    if flagged and flagged != "all":
        norm_flagged = flagged.strip().lower()
        if norm_flagged in ("true", "1", "yes", "flagged"):
            qs = qs.filter(is_flagged=True)
        elif norm_flagged in ("false", "0", "no", "unflagged"):
            qs = qs.filter(is_flagged=False)
        elif norm_flagged == "confirmed":
            qs = qs.filter(is_flagged=True, is_flag_confirmed=True)
        elif norm_flagged == "unconfirmed":
            qs = qs.filter(is_flagged=True, is_flag_confirmed=False)

    return qs.order_by("-created_at")
