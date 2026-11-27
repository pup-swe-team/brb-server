"""Tests for CP-1103 Admin review queues (verification, reports, unreturned cases)."""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.audit.models import AdminAccessLog
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.notifications.models import Notification
from apps.orders.models import (
    Order,
    OrderStatus,
    OrderStatusOverride,
    UnreturnedCase,
    UnreturnedCaseStatus,
)
from apps.reports.models import (
    ListingReport,
    ListingReportCategory,
    UserReport,
    UserReportCategory,
)
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)


class AdminReviewQueuesAPITests(APITestCase):
    def setUp(self) -> None:
        self.today = timezone.localdate()
        self.admin = User.objects.create_superuser(
            email="queues-admin@pup.edu.ph",
            password="StrongPassword123!",
            full_name="Queue Admin",
            contact_number="09111111111",
        )
        self.lender = User.objects.create_user(
            email="queues-lender@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Queue Lender",
            contact_number="09123456789",
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        self.borrower = User.objects.create_user(
            email="queues-borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Queue Borrower",
            contact_number="09987654321",
            account_status=User.AccountStatusChoices.SUSPENDED,
        )

        # 1. Pending identity verification document
        pending_doc_st, _ = IdentityDocumentStatus.objects.get_or_create(name="pending")
        pup_id_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        self.doc = IdentityDocument.objects.create(
            user=self.borrower,
            document_type=pup_id_type,
            id_number="2024-11030-MN-0",
            document_data=b"fake-id-bytes",
            status=pending_doc_st,
            consent_given=True,
            consented_at=timezone.now(),
        )

        # 2. Open reports (user + listing)
        category = ListingCategory.objects.create(name="Lab Equipment")
        pickup = PickupLocation.objects.create(name="South Wing")
        active_st, _ = ListingStatus.objects.get_or_create(name="active")
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Digital Multimeter",
            description="Good condition",
            category=category,
            pickup_location=pickup,
            status=active_st,
        )
        u_cat, _ = UserReportCategory.objects.get_or_create(name="harassment")
        self.user_report = UserReport.objects.create(
            reporter=self.lender,
            target_user=self.borrower,
            category=u_cat,
            description="Abusive language",
            status="open",
        )
        l_cat, _ = ListingReportCategory.objects.get_or_create(name="prohibited")
        self.listing_report = ListingReport.objects.create(
            reporter=self.borrower,
            target_listing=self.listing,
            category=l_cat,
            description="Prohibited item",
            status="open",
        )

        # 3. Open unreturned case
        unreturned_order_st, _ = OrderStatus.objects.get_or_create(name="unreturned")
        self.order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=self.today - timedelta(days=20),
            end_date=self.today - timedelta(days=12),
            status=unreturned_order_st,
        )
        open_case_st, _ = UnreturnedCaseStatus.objects.get_or_create(name="open")
        self.unreturned_case = UnreturnedCase.objects.create(
            order=self.order,
            status=open_case_st,
        )

    def test_review_queues_requires_admin(self) -> None:
        res_anon = self.client.get(reverse("api-admin-review-queues"))
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.lender)
        res_non_staff = self.client.get(reverse("api-admin-review-queues"))
        self.assertEqual(res_non_staff.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_queues_aggregates_all_three_sources_and_filters(self) -> None:
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse("api-admin-review-queues"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["counts"]["verification"], 1)
        self.assertEqual(data["counts"]["reports"], 2)
        self.assertEqual(data["counts"]["unreturned_cases"], 1)
        self.assertEqual(data["counts"]["total_open"], 4)
        self.assertEqual(len(data["items"]), 4)
        queue_types = {item["queue_type"] for item in data["items"]}
        self.assertEqual(queue_types, {"verification", "report", "unreturned_case"})

        # Filter by single queue type
        res_v = self.client.get(
            reverse("api-admin-review-queues") + "?type=verification&status=open"
        )
        self.assertEqual(res_v.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_v.json()["items"]), 1)
        self.assertEqual(res_v.json()["items"][0]["queue_type"], "verification")

        # Direct list endpoints
        v_list = self.client.get(reverse("api-admin-verifications"))
        self.assertEqual(v_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(v_list.json()), 1)

        r_list = self.client.get(reverse("api-admin-reports"))
        self.assertEqual(r_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r_list.json()), 2)

    def test_unified_action_verification_reject_requires_reason_and_approve_persists(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.admin)
        url = reverse(
            "api-admin-review-queue-action",
            kwargs={"queue_type": "verification", "pk": self.doc.pk},
        )
        # Reject without reason -> 400
        bad_res = self.client.post(url, {"action": "reject"}, format="json")
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Approve -> 200, status persisted + AdminAccessLog recorded
        ok_res = self.client.post(url, {"action": "approve"}, format="json")
        self.assertEqual(ok_res.status_code, status.HTTP_200_OK)
        self.assertEqual(ok_res.json()["item"]["status"], "approved")

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status.name, "approved")
        self.assertEqual(self.doc.reviewed_by, self.admin)
        self.assertTrue(
            AdminAccessLog.objects.filter(
                document=self.doc, admin=self.admin, action="review"
            ).exists()
        )

        # Repeat review -> 409 Conflict
        repeat_res = self.client.post(url, {"action": "approve"}, format="json")
        self.assertEqual(repeat_res.status_code, status.HTTP_409_CONFLICT)

    def test_report_resolution_persists_audit_fields_and_blocks_double_resolve(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.admin)
        # Resolve user report via unified queue action endpoint
        action_url = reverse(
            "api-admin-review-queue-action",
            kwargs={"queue_type": "report_user", "pk": self.user_report.pk},
        )
        res = self.client.post(
            action_url,
            {"action": "resolve", "resolution_notes": "Warned user"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.user_report.refresh_from_db()
        self.assertEqual(self.user_report.status, "resolved")
        self.assertEqual(self.user_report.resolved_by, self.admin)
        self.assertIsNotNone(self.user_report.resolved_at)
        self.assertEqual(self.user_report.resolution_notes, "Warned user")
        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name="report_updates",
                reference_id=str(self.user_report.pk),
            ).exists()
        )

        # Double resolve -> 409
        repeat = self.client.post(action_url, {"action": "resolve"}, format="json")
        self.assertEqual(repeat.status_code, status.HTTP_409_CONFLICT)

        # Resolve listing report via direct admin report endpoint
        direct_url = reverse(
            "api-admin-report-resolve",
            kwargs={"report_type": "listing", "pk": self.listing_report.pk},
        )
        direct_res = self.client.post(
            direct_url, {"resolution_notes": "Listing removed"}, format="json"
        )
        self.assertEqual(direct_res.status_code, status.HTTP_200_OK)
        self.assertEqual(direct_res.json()["status"], "resolved")
        self.assertEqual(direct_res.json()["resolved_by_id"], self.admin.pk)

    def test_unreturned_case_escalate_and_close_returned_via_unified_queue(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.admin)
        action_url = reverse(
            "api-admin-review-queue-action",
            kwargs={
                "queue_type": "unreturned_case",
                "pk": self.unreturned_case.pk,
            },
        )
        esc_res = self.client.post(
            action_url,
            {"action": "escalate", "resolution_notes": "Forwarded to PUP OSS"},
            format="json",
        )
        self.assertEqual(esc_res.status_code, status.HTTP_200_OK)
        self.unreturned_case.refresh_from_db()
        self.assertEqual(self.unreturned_case.status.name, "escalated")

        close_res = self.client.post(
            action_url,
            {
                "action": "close",
                "status": "returned",
                "resolution_notes": "Item recovered via OSS",
            },
            format="json",
        )
        self.assertEqual(close_res.status_code, status.HTTP_200_OK)
        self.unreturned_case.refresh_from_db()
        self.order.refresh_from_db()
        self.borrower.refresh_from_db()
        self.assertEqual(self.unreturned_case.status.name, "returned")
        self.assertEqual(self.order.status.name, "returned")
        self.assertEqual(self.borrower.account_status, User.AccountStatusChoices.ACTIVE)
        self.assertTrue(
            OrderStatusOverride.objects.filter(
                order=self.order, admin=self.admin, new_status="returned"
            ).exists()
        )
