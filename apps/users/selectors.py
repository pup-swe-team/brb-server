from django.db.models import Count, Q, QuerySet

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
