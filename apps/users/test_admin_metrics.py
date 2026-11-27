"""Tests for Admin dashboard summary metrics aggregation endpoint (CP-1107)."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.chat.models import Conversation, Message
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.orders.constants import ALL_ORDER_STATUSES
from apps.orders.models import (
    Dispute,
    Order,
    OrderStatus,
    UnreturnedCase,
    UnreturnedCaseStatus,
)
from apps.reports.models import (
    ListingReport,
    ListingReportCategory,
    MessageReport,
    MessageReportCategory,
    ReviewReport,
    ReviewReportCategory,
    UserReport,
    UserReportCategory,
)
from apps.reviews.models import Review
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)


class AdminMetricsEndpointTests(APITestCase):
    """CP-1107: GET /api/v1/admin/metrics/ and /api/v1/admin/dashboard/metrics/."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            email="metrics-admin@pup.edu.ph",
            password="StrongPassword123!",
            full_name="Metrics Admin",
            contact_number="09111111111",
        )
        self.lender = User.objects.create_user(
            email="metrics-lender@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Metrics Lender",
            contact_number="09122222222",
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        self.borrower = User.objects.create_user(
            email="metrics-borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Metrics Borrower",
            contact_number="09133333333",
        )
        self.flagged_user = User.objects.create_user(
            email="metrics-flagged@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Flagged Member",
            contact_number="09144444444",
            is_flagged=True,
        )

        # Identity documents: 1 pending (3 days old), 1 approved
        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        pending_doc_status, _ = IdentityDocumentStatus.objects.get_or_create(
            name="pending"
        )
        approved_doc_status, _ = IdentityDocumentStatus.objects.get_or_create(
            name="approved"
        )

        pending_doc = IdentityDocument.objects.create(
            user=self.borrower,
            document_type=doc_type,
            id_number="2024-10001-MN-0",
            document_data=b"img",
            status=pending_doc_status,
        )
        IdentityDocument.objects.filter(pk=pending_doc.pk).update(
            submitted_at=timezone.now() - timedelta(days=3)
        )
        IdentityDocument.objects.create(
            user=self.lender,
            document_type=doc_type,
            id_number="2024-10002-MN-0",
            document_data=b"img",
            status=approved_doc_status,
        )

        # Listings: 2 active, 1 deactivated
        cat = ListingCategory.objects.create(name="Electronics")
        loc = PickupLocation.objects.create(name="PUP Main Gate")
        active_listing_status, _ = ListingStatus.objects.get_or_create(name="active")
        deactivated_listing_status, _ = ListingStatus.objects.get_or_create(
            name="deactivated"
        )

        self.listing_active_1 = Listing.objects.create(
            lender=self.lender,
            title="Oscilloscope",
            description="Working unit",
            category=cat,
            pickup_location=loc,
            status=active_listing_status,
        )
        self.listing_active_2 = Listing.objects.create(
            lender=self.lender,
            title="Multimeter",
            description="Digital meter",
            category=cat,
            pickup_location=loc,
            status=active_listing_status,
        )
        Listing.objects.create(
            lender=self.lender,
            title="Old Soldering Iron",
            description="Inactive",
            category=cat,
            pickup_location=loc,
            status=deactivated_listing_status,
        )

        # Orders: one order for each of the 11 lifecycle statuses
        today = timezone.localdate()
        self.orders_by_status: dict[str, Order] = {}
        for status_name in ALL_ORDER_STATUSES:
            order_status, _ = OrderStatus.objects.get_or_create(name=status_name)
            self.orders_by_status[status_name] = Order.objects.create(
                listing=self.listing_active_1,
                borrower=self.borrower,
                start_date=today,
                end_date=today + timedelta(days=2),
                status=order_status,
            )

        # Reports: 1 open of each type + 1 resolved UserReport (should not count as open)
        user_cat, _ = UserReportCategory.objects.get_or_create(name="harassment")
        listing_cat, _ = ListingReportCategory.objects.get_or_create(name="prohibited")
        review_cat, _ = ReviewReportCategory.objects.get_or_create(name="spam")
        msg_cat, _ = MessageReportCategory.objects.get_or_create(name="threats")

        UserReport.objects.create(
            reporter=self.borrower,
            target_user=self.flagged_user,
            category=user_cat,
            description="Open user report",
            status="open",
        )
        UserReport.objects.create(
            reporter=self.lender,
            target_user=self.flagged_user,
            category=user_cat,
            description="Resolved user report",
            status="resolved",
        )
        ListingReport.objects.create(
            reporter=self.borrower,
            target_listing=self.listing_active_2,
            category=listing_cat,
            description="Open listing report",
            status="open",
        )
        review = Review.objects.create(
            order=self.orders_by_status["completed"],
            reviewer=self.borrower,
            rating=1,
            comment="Bad item",
        )
        ReviewReport.objects.create(
            reporter=self.lender,
            target_review=review,
            category=review_cat,
            description="Open review report",
            status="open",
        )
        conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.lender,
            order=self.orders_by_status["active"],
        )
        msg = Message.objects.create(
            conversation=conv,
            sender=self.flagged_user,
            content="Suspicious message",
        )
        MessageReport.objects.create(
            reporter=self.borrower,
            target_message=msg,
            category=msg_cat,
            description="Open message report",
            status="open",
        )

        # Disputes: 1 open, 1 resolved
        Dispute.objects.create(
            order=self.orders_by_status["disputed"],
            raised_by=self.lender,
            description="Cracked screen",
            status=Dispute.StatusChoices.OPEN,
        )
        Dispute.objects.create(
            order=self.orders_by_status["completed"],
            raised_by=self.lender,
            description="Old dispute",
            status=Dispute.StatusChoices.RESOLVED,
        )

        # Unreturned cases: 1 open, 1 returned (closed)
        open_case_status, _ = UnreturnedCaseStatus.objects.get_or_create(name="open")
        returned_case_status, _ = UnreturnedCaseStatus.objects.get_or_create(
            name="returned"
        )
        UnreturnedCase.objects.create(
            order=self.orders_by_status["unreturned"],
            status=open_case_status,
        )
        UnreturnedCase.objects.create(
            order=self.orders_by_status["returned"],
            status=returned_case_status,
        )

    def test_anonymous_and_non_admin_are_rejected(self) -> None:
        url = reverse("api-admin-metrics")
        anon_res = self.client.get(url)
        self.assertEqual(anon_res.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.borrower)
        member_res = self.client.get(url)
        self.assertEqual(member_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_metrics_aggregation_endpoint_returns_expected_counts(self) -> None:
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse("api-admin-metrics"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["total_users"], 4)
        self.assertEqual(data["active_listings"], 2)
        self.assertEqual(data["listings"]["total"], 3)
        self.assertEqual(data["listings"]["by_status"]["deactivated"], 1)
        self.assertEqual(data["open_reports"], 4)
        self.assertEqual(
            data["reports"]["by_type"],
            {"user": 1, "listing": 1, "review": 1, "message": 1},
        )
        self.assertEqual(data["reports"]["flagged_users_pending_review"], 1)
        self.assertEqual(data["pending_verifications"], 1)
        self.assertEqual(data["oldest_pending_verification_days"], 3)
        self.assertEqual(data["open_disputes"], 1)
        self.assertEqual(data["open_unreturned_cases"], 1)
        self.assertEqual(data["total_orders"], len(ALL_ORDER_STATUSES))
        for status_name in ALL_ORDER_STATUSES:
            self.assertEqual(data["orders_by_status"][status_name], 1)

        # Alias route returns the exact same metrics structure
        alias_res = self.client.get(reverse("api-admin-dashboard-metrics"))
        self.assertEqual(alias_res.status_code, status.HTTP_200_OK)
        self.assertEqual(alias_res.json()["total_users"], data["total_users"])
        self.assertEqual(alias_res.json()["open_reports"], data["open_reports"])

    def test_portal_dashboard_matches_metrics_endpoint(self) -> None:
        self.client.force_authenticate(user=self.admin)
        api_data = self.client.get(reverse("api-admin-metrics")).json()

        self.client.force_login(self.admin)
        portal_res = self.client.get(reverse("portal-dashboard"))
        self.assertEqual(portal_res.status_code, status.HTTP_200_OK)
        stats = portal_res.context["stats"]

        self.assertEqual(stats["total_users"], api_data["total_users"])
        self.assertEqual(stats["active_listings"], api_data["active_listings"])
        self.assertEqual(stats["open_reports"], api_data["open_reports"])
        self.assertEqual(
            stats["pending_verifications"], api_data["pending_verifications"]
        )
        self.assertEqual(stats["open_disputes"], api_data["open_disputes"])
        self.assertEqual(
            stats["open_unreturned_cases"], api_data["open_unreturned_cases"]
        )
        self.assertEqual(stats["total_orders"], api_data["total_orders"])
