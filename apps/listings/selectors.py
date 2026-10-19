from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.users.models import User

from .models import BlockedDateRange, Listing


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
