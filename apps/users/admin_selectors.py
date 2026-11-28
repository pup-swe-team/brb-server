"""Shared read-selectors for Admin dashboard summary metrics (CP-1107).

Both the DRF metrics-aggregation endpoint (`GET /api/v1/admin/metrics/`) and
the server-rendered CoPUPAdmin portal dashboard (`GET /portal/`) read from
`get_admin_dashboard_metrics()` so the UI and API never drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, Min, Q
from django.utils import timezone

from apps.listings.models import Listing
from apps.orders.constants import (
    ALL_ORDER_STATUSES,
    UNRETURNED_CASE_STATUS_ESCALATED,
    UNRETURNED_CASE_STATUS_OPEN,
)
from apps.orders.models import Dispute, Order, UnreturnedCase
from apps.reports.constants import REPORT_STATUS_OPEN
from apps.reports.models import (
    ListingReport,
    MessageReport,
    ReviewReport,
    UserReport,
)

from .constants import IDENTITY_DOCUMENT_STATUS_PENDING
from .models import IdentityDocument, User

LISTING_STATUS_KEYS = ("active", "deactivated", "deleted")


def _open_reports_by_type() -> dict[str, int]:
    """Count open reports in each of the four report tables."""
    return {
        "user": UserReport.objects.filter(status=REPORT_STATUS_OPEN).count(),
        "listing": ListingReport.objects.filter(status=REPORT_STATUS_OPEN).count(),
        "review": ReviewReport.objects.filter(status=REPORT_STATUS_OPEN).count(),
        "message": MessageReport.objects.filter(status=REPORT_STATUS_OPEN).count(),
    }


def _flagged_users_pending_review_count() -> int:
    """Count accounts auto-flagged or pending review that have not been confirmed yet."""
    return User.objects.filter(
        Q(is_flagged=True, is_flag_confirmed=False)
        | Q(account_status=User.AccountStatusChoices.PENDING_REVIEW)
    ).count()


def get_portal_nav_counts() -> dict[str, int]:
    """Consistent sidebar badge counts shared across all CoPUPAdmin portal views."""
    pending_verifications = IdentityDocument.objects.filter(
        status__name=IDENTITY_DOCUMENT_STATUS_PENDING
    ).count()
    open_reports_total = sum(_open_reports_by_type().values())
    open_unreturned_cases = UnreturnedCase.objects.filter(
        status__name__in=(
            UNRETURNED_CASE_STATUS_OPEN,
            UNRETURNED_CASE_STATUS_ESCALATED,
        )
    ).count()
    open_disputes = Dispute.objects.filter(
        status__in=(Dispute.StatusChoices.OPEN, Dispute.StatusChoices.ESCALATED)
    ).count()

    return {
        "nav_verification_count": pending_verifications,
        "nav_reports_count": open_reports_total,
        "nav_unreturned_count": open_unreturned_cases,
        "nav_disputes_count": open_disputes,
    }


def get_admin_dashboard_metrics(*, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate platform-wide operational metrics for the Admin dashboard (CP-1107)."""
    current_time = now or timezone.now()
    month_start = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = current_time - timedelta(days=7)

    # 1. Users breakdown (single aggregate query for status buckets & KPIs)
    user_stats = User.objects.aggregate(
        total=Count("id"),
        new_this_month=Count("id", filter=Q(created_at__gte=month_start)),
        active_lenders=Count(
            "id", filter=Q(lender_status=User.LenderStatusChoices.ACTIVE)
        ),
        flagged_pending=Count(
            "id",
            filter=Q(is_flagged=True, is_flag_confirmed=False)
            | Q(account_status=User.AccountStatusChoices.PENDING_REVIEW),
        ),
        **{
            f"status_{choice.value}": Count("id", filter=Q(account_status=choice.value))
            for choice in User.AccountStatusChoices
        },
    )
    users_by_status = {
        choice.value: (user_stats[f"status_{choice.value}"] or 0)
        for choice in User.AccountStatusChoices
    }
    total_users = user_stats["total"] or 0
    new_users_this_month = user_stats["new_this_month"] or 0
    active_lenders = user_stats["active_lenders"] or 0
    flagged_users_pending = user_stats["flagged_pending"] or 0

    # 2. Listings breakdown (single aggregate query for status counts & weekly adds)
    listing_stats = Listing.objects.aggregate(
        total=Count("id"),
        added_this_week=Count("id", filter=Q(created_at__gte=week_start)),
        **{
            f"status_{key}": Count("id", filter=Q(status__name=key))
            for key in LISTING_STATUS_KEYS
        },
    )
    listings_by_status = {
        key: (listing_stats[f"status_{key}"] or 0) for key in LISTING_STATUS_KEYS
    }
    total_listings = listing_stats["total"] or 0
    active_listings = listings_by_status["active"]
    listings_added_this_week = listing_stats["added_this_week"] or 0

    # 3. Orders by status (single GROUP BY seeded with all 11 lifecycle statuses)
    orders_by_status = {status_name: 0 for status_name in ALL_ORDER_STATUSES}
    total_orders = 0
    for row in Order.objects.values("status__name").annotate(total=Count("id")):
        status_name = row["status__name"]
        count = row["total"]
        if status_name in orders_by_status:
            orders_by_status[status_name] = count
        total_orders += count

    # 4. Open reports across all 4 report models
    reports_by_type = _open_reports_by_type()
    total_open_reports = sum(reports_by_type.values())

    # 5. Review queues & moderation backlog (single aggregate query)
    pending_doc_stats = IdentityDocument.objects.filter(
        status__name=IDENTITY_DOCUMENT_STATUS_PENDING
    ).aggregate(
        total=Count("id"),
        oldest=Min("submitted_at"),
    )
    pending_verifications = pending_doc_stats["total"] or 0
    oldest_waiting = pending_doc_stats["oldest"]
    oldest_pending_days = (
        max(0, (current_time - oldest_waiting).days)
        if oldest_waiting is not None
        else None
    )

    open_unreturned_cases = UnreturnedCase.objects.filter(
        status__name__in=(
            UNRETURNED_CASE_STATUS_OPEN,
            UNRETURNED_CASE_STATUS_ESCALATED,
        )
    ).count()
    open_disputes = Dispute.objects.filter(
        status__in=(Dispute.StatusChoices.OPEN, Dispute.StatusChoices.ESCALATED)
    ).count()

    return {
        "total_users": total_users,
        "new_users_this_month": new_users_this_month,
        "active_listings": active_listings,
        "listings_added_this_week": listings_added_this_week,
        "open_reports": total_open_reports,
        "pending_verifications": pending_verifications,
        "oldest_pending_verification_days": oldest_pending_days,
        "open_unreturned_cases": open_unreturned_cases,
        "open_disputes": open_disputes,
        "total_orders": total_orders,
        "orders_by_status": orders_by_status,
        "users": {
            "total": total_users,
            "new_this_month": new_users_this_month,
            "active_lenders": active_lenders,
            "flagged_pending_review": flagged_users_pending,
            "by_account_status": users_by_status,
        },
        "listings": {
            "total": total_listings,
            "active": active_listings,
            "added_this_week": listings_added_this_week,
            "by_status": listings_by_status,
        },
        "reports": {
            "total_open": total_open_reports,
            "by_type": reports_by_type,
            "flagged_users_pending_review": flagged_users_pending,
        },
        "review_queues": {
            "pending_verifications": pending_verifications,
            "oldest_pending_verification_days": oldest_pending_days,
            "open_reports": total_open_reports,
            "open_unreturned_cases": open_unreturned_cases,
            "open_disputes": open_disputes,
        },
        "generated_at": current_time.isoformat(),
    }
