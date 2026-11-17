"""
Comprehensive end-to-end integration tests between brb-server and brb-client.
Validates the exact HTTP endpoints, payloads, queries, and responses used by:
- src/features/reviews/services/reviewsService.ts (CP-601)
- src/features/notifications/services/notificationsService.ts (CP-801)
- src/features/reports/services/reportsService.ts (CP-901)
- src/features/profile/services/lenderProfile.ts (CP-601 / TC-101)
- src/features/profile/services/lenderRoleService.ts (CP-205)
- src/features/orders/services/ordersService.ts (CP-202 / CP-503)
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.listings.models import (
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.constants import NOTIFICATION_TYPE_ACCEPTANCE
from apps.notifications.services import create_notification
from apps.orders.models import Order, OrderStatus
from apps.reviews.models import Review

User = get_user_model()


class FrontendBackendLiveIntegrationTests(APITestCase):
    """Direct integration test simulating brb-client API calls with USE_MOCK=false."""

    def setUp(self) -> None:
        self.borrower = User.objects.create_user(
            email="fe.borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower User",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.borrower.account_status = User.AccountStatusChoices.ACTIVE
        self.borrower.save(update_fields=["account_status"])

        self.lender = User.objects.create_user(
            email="fe.lender@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender User",
            affiliation=User.AffiliationChoices.STUDENT,
            bio="Electronics and lab tools",
        )
        self.lender.account_status = User.AccountStatusChoices.ACTIVE
        self.lender.lender_status = User.LenderStatusChoices.ACTIVE
        self.lender.save(update_fields=["account_status", "lender_status"])

        self.category, _ = ListingCategory.objects.get_or_create(name="Tools")
        self.location, _ = PickupLocation.objects.get_or_create(
            name="Main Gate", defaults={"description": "Guard post"}
        )
        self.active_listing_status, _ = ListingStatus.objects.get_or_create(
            name="active"
        )

        self.listing = Listing.objects.create(
            lender=self.lender,
            category=self.category,
            pickup_location=self.location,
            status=self.active_listing_status,
            title="Digital Multimeter",
            description="Precision multimeter",
            condition="like_new",
            rate_per_day=Decimal("15.00"),
            is_ownership_confirmed=True,
        )

        self.completed_status, _ = OrderStatus.objects.get_or_create(name="completed")
        self.confirmed_status, _ = OrderStatus.objects.get_or_create(name="confirmed")
        self.requested_status, _ = OrderStatus.objects.get_or_create(name="requested")

        today = timezone.localdate()
        self.completed_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=self.completed_status,
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=2),
            completed_at=timezone.now() - timedelta(days=2),
        )

    # --------------------------------------------------------------------------
    # CP-601: Reviews & Ratings Integration (reviewsService.ts)
    # --------------------------------------------------------------------------
    def test_cp601_reviews_service_flow(self) -> None:
        """Simulates getOrderReview() and submitReview() from reviewsService.ts."""
        self.client.force_authenticate(user=self.borrower)

        # 1. Frontend calls getOrderReview(orderId) before reviewing: expects null (404)
        get_before = self.client.get(
            f"/api/v1/orders/{self.completed_order.pk}/review/"
        )
        self.assertEqual(get_before.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Frontend calls submitReview({ orderId, rating, comment })
        submit_res = self.client.post(
            "/api/v1/reviews/",
            {
                "order_id": self.completed_order.pk,
                "rating": 5,
                "comment": "Tool was in perfect condition!",
            },
            format="json",
        )
        self.assertEqual(submit_res.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", submit_res.data)
        self.assertEqual(submit_res.data["rating"], 5)
        self.assertEqual(submit_res.data["comment"], "Tool was in perfect condition!")
        self.assertIn("can_report", submit_res.data)
        self.assertIn("report_url", submit_res.data)

        # 3. Frontend calls getOrderReview(orderId) after reviewing: expects review object
        get_after = self.client.get(f"/api/v1/orders/{self.completed_order.pk}/review/")
        self.assertEqual(get_after.status_code, status.HTTP_200_OK)
        self.assertEqual(get_after.data["id"], submit_res.data["id"])
        self.assertEqual(get_after.data["rating"], 5)

        # 4. ReviewsSection & LenderProfileScreen call getLenderProfile(lenderId)
        profile_res = self.client.get(f"/api/v1/lenders/{self.lender.pk}/")
        self.assertEqual(profile_res.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_res.data["average_rating"], 5.0)
        self.assertEqual(profile_res.data["review_count"], 1)
        self.assertIn("reviews", profile_res.data)
        self.assertEqual(len(profile_res.data["reviews"]), 1)
        self.assertEqual(
            profile_res.data["reviews"][0]["comment"], "Tool was in perfect condition!"
        )

    # --------------------------------------------------------------------------
    # CP-801: Notifications Integration (notificationsService.ts)
    # --------------------------------------------------------------------------
    def test_cp801_notifications_service_flow(self) -> None:
        """Simulates getNotifications() and markAsRead() from notificationsService.ts."""
        notif = create_notification(
            user=self.borrower,
            event_name=NOTIFICATION_TYPE_ACCEPTANCE,
            reference_id=str(self.completed_order.pk),
        )

        self.client.force_authenticate(user=self.borrower)

        # 1. Frontend calls getNotifications()
        list_res = self.client.get("/api/v1/notifications/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        results = list_res.data.get("results", list_res.data)
        self.assertGreaterEqual(len(results), 1)

        target_notif = next(n for n in results if n["id"] == notif.pk)
        # Check that order_id is present so NotificationsScreen navigates to OrderDetail
        self.assertEqual(target_notif["order_id"], self.completed_order.pk)
        self.assertFalse(target_notif["is_read"])

        # 2. Frontend calls markAsRead(id)
        read_res = self.client.post(f"/api/v1/notifications/{notif.pk}/read/")
        self.assertEqual(read_res.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

        # 3. Frontend calls markAllAsRead()
        read_all_res = self.client.post("/api/v1/notifications/read-all/")
        self.assertEqual(read_all_res.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # CP-901: Reporting System Integration (reportsService.ts / ReportSheet.tsx)
    # --------------------------------------------------------------------------
    def test_cp901_reports_service_flow(self) -> None:
        """Simulates submitReport() from reportsService.ts using ReportSheet options."""
        self.client.force_authenticate(user=self.borrower)

        # 1. Report user with 'fraud' and string targetId 'u<id>'
        res_user_report = self.client.post(
            "/api/v1/reports/",
            {
                "target_type": "user",
                "target_id": f"u{self.lender.pk}",
                "category": "fraud",
                "description": "Suspicious account behavior reported via ReportSheet modal.",
            },
            format="json",
        )
        self.assertEqual(res_user_report.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_user_report.data["status"], "open")
        self.assertEqual(res_user_report.data["category"], "scam_fraud")

        # 2. Report listing with 'prohibited_item'
        res_listing_report = self.client.post(
            "/api/v1/reports/",
            {
                "target_type": "listing",
                "target_id": str(self.listing.pk),
                "category": "prohibited_item",
                "description": "Reported prohibited item from ReportSheet modal.",
            },
            format="json",
        )
        self.assertEqual(res_listing_report.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_listing_report.data["status"], "open")
        self.assertEqual(res_listing_report.data["category"], "prohibited")

        # 3. Report review with 'other'
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.lender,
            rating=4,
            comment="Good borrower",
        )
        res_review_report = self.client.post(
            "/api/v1/reports/",
            {
                "target_type": "review",
                "target_id": review.pk,
                "category": "other",
                "description": "Other issue with review.",
            },
            format="json",
        )
        self.assertEqual(res_review_report.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_review_report.data["status"], "open")
        self.assertEqual(res_review_report.data["category"], "other")

    # --------------------------------------------------------------------------
    # CP-205: Revoke Lender Role Integration (lenderRoleService.ts)
    # --------------------------------------------------------------------------
    def test_cp205_revoke_lender_role_flow(self) -> None:
        """Simulates revokeLenderRole() and RevokeBlockedError from lenderRoleService.ts."""
        self.client.force_authenticate(user=self.lender)

        # 1. When an active or confirmed order exists -> HTTP 409 Conflict (RevokeBlockedError)
        active_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=self.confirmed_status,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=2),
        )

        res_blocked = self.client.post("/api/v1/auth/revoke-lender/")
        self.assertEqual(res_blocked.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_blocked.data["code"], "lender_revocation_blocked")

        # 2. When active order is resolved -> Revocation succeeds (HTTP 200)
        active_order.status = self.completed_status
        active_order.save(update_fields=["status"])

        res_ok = self.client.post("/api/v1/auth/revoke-lender/")
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.lender.refresh_from_db()
        self.assertEqual(self.lender.lender_status, User.LenderStatusChoices.REVOKED)

    # --------------------------------------------------------------------------
    # CP-202: Order Cancel and Dashboard Integration (ordersService.ts)
    # --------------------------------------------------------------------------
    def test_cp202_cancel_order_and_dashboard_flow(self) -> None:
        """Simulates cancelOrder() and Borrower Dashboard actions from ordersService.ts."""
        self.client.force_authenticate(user=self.borrower)

        pending_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=self.requested_status,
            start_date=timezone.localdate() + timedelta(days=3),
            end_date=timezone.localdate() + timedelta(days=5),
        )

        # 1. cancelOrder(orderId, reason, details)
        cancel_res = self.client.post(
            f"/api/v1/orders/{pending_order.pk}/cancel/",
            {"reason": "Change of schedule: need to cancel before pickup"},
            format="json",
        )
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.data["status"], "cancelled")

        # 2. Borrower Dashboard reflects cancel_reason
        dash_res = self.client.get("/api/v1/dashboard/borrower/")
        self.assertEqual(dash_res.status_code, status.HTTP_200_OK)
        cancelled_orders = dash_res.data["orders"]["cancelled"]
        cancelled_entry = next(
            (o for o in cancelled_orders if o["id"] == pending_order.pk), None
        )
        self.assertIsNotNone(cancelled_entry)
        self.assertEqual(
            cancelled_entry["cancel_reason"],
            "Change of schedule: need to cancel before pickup",
        )

    def test_bug1_unverified_account_past_7_days_is_deactivated(self) -> None:
        """Bug 1 / TC-007: Unverified account older than 7 days is purged on login/resend/verify."""
        # 1. Create an unverified user whose created_at is 8 days ago
        unverified_user = User.objects.create_user(
            email="stale.unverified@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Stale Student",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        User.objects.filter(pk=unverified_user.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        unverified_user.refresh_from_db()

        # 2. Attempt login after 8 days -> blocked and account purged
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "stale.unverified@iskolarngbayan.pup.edu.ph",
                "password": "StrongPassword123!",
            },
            format="json",
        )
        self.assertEqual(login_res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("deactivated", str(login_res.data))
        self.assertFalse(
            User.objects.filter(
                email="stale.unverified@iskolarngbayan.pup.edu.ph"
            ).exists()
        )

        # 3. Create another unverified user > 7 days ago and test resend verification
        unverified_user2 = User.objects.create_user(
            email="stale.resend@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Stale Resend",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        unverified_user2.account_status = User.AccountStatusChoices.PENDING_REVIEW
        unverified_user2.save(update_fields=["account_status"])
        User.objects.filter(pk=unverified_user2.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        resend_res = self.client.post(
            "/api/v1/auth/resend-verification/",
            {"email": "stale.resend@iskolarngbayan.pup.edu.ph"},
            format="json",
        )
        self.assertEqual(resend_res.status_code, status.HTTP_200_OK)
        # Verify account was purged
        self.assertFalse(
            User.objects.filter(email="stale.resend@iskolarngbayan.pup.edu.ph").exists()
        )

    def test_bug2_order_status_updates_to_expired_and_overdue_with_time(self) -> None:
        """Bug 2: Requested orders past start_date expire; Active orders past end_date become Overdue."""
        today = timezone.localdate()

        # 1. Requested order whose start_date is in the past (e.g. yesterday)
        stale_request = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=self.requested_status,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=2),
        )

        # 2. Active order whose end_date is in the past (e.g. yesterday)
        active_status, _ = OrderStatus.objects.get_or_create(name="active")
        overdue_candidate = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=active_status,
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=1),
        )

        # 3. Accessing borrower dashboard triggers on-access sweep in Asia/Manila
        self.client.force_authenticate(user=self.borrower)
        dash_res = self.client.get("/api/v1/dashboard/borrower/")
        self.assertEqual(dash_res.status_code, status.HTTP_200_OK)

        stale_request.refresh_from_db()
        overdue_candidate.refresh_from_db()

        self.assertEqual(stale_request.status.name, "expired")
        self.assertEqual(overdue_candidate.status.name, "overdue")
