"""Tests for reporting users, listings, reviews, and messages (CP-901) and auto-flagging (CP-902)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.chat.models import Conversation, Message
from apps.listings.models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.listings.services import create_listing
from apps.orders.models import Order, OrderStatus
from apps.orders.services import request_borrow
from apps.reports.models import (
    ListingReport,
    MessageReport,
    ReviewReport,
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


class ReportSubmissionTests(TestCase):
    """Test suite for CP-901 report submission and one-report-per-interaction enforcement."""

    def setUp(self) -> None:
        self.client = APIClient()

        self.lender = User.objects.create_user(
            email="lender_cp901@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender CP901",
            contact_number="09171110901",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.borrower = User.objects.create_user(
            email="borrower_cp901@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower CP901",
            contact_number="09172220901",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.outsider = User.objects.create_user(
            email="outsider_cp901@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Outsider CP901",
            contact_number="09173330901",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Books")
        self.pickup_location, _ = PickupLocation.objects.get_or_create(
            name="Main Library",
            defaults={"description": "Entrance"},
        )
        self.listing_active, _ = ListingStatus.objects.get_or_create(name="active")
        self.listing = Listing.objects.create(
            lender=self.lender,
            category=self.category,
            pickup_location=self.pickup_location,
            status=self.listing_active,
            title="Calculus Early Transcendentals",
            description="8th edition textbook",
            condition="good",
            rate_per_day=Decimal("30.00"),
            is_ownership_confirmed=True,
        )

        self.status_completed, _ = OrderStatus.objects.get_or_create(name="completed")
        self.order1 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 3),
            status=self.status_completed,
        )
        self.order2 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 6),
            status=self.status_completed,
        )

        self.review = Review.objects.create(
            order=self.order1,
            reviewer=self.borrower,
            rating=2,
            comment="Item had torn pages.",
        )

        u_a, u_b = (
            (self.borrower, self.lender)
            if self.borrower.pk < self.lender.pk
            else (self.lender, self.borrower)
        )
        self.conversation = Conversation.objects.create(
            user_a=u_a,
            user_b=u_b,
            listing=self.listing,
            order=self.order1,
        )
        self.message = Message.objects.create(
            conversation=self.conversation,
            sender=self.lender,
            content="Send payment outside the agreed terms.",
        )

    def test_list_report_categories_returns_seeded_categories(self) -> None:
        """GET /api/v1/reports/categories/ returns seeded categories for all 4 target types."""
        self.client.force_authenticate(user=self.borrower)
        resp = self.client.get("/api/v1/reports/categories/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for key in ("user", "listing", "review", "message"):
            self.assertIn(key, resp.data)
            self.assertGreaterEqual(len(resp.data[key]), 5)

    def test_submit_user_report_creates_open_entry_and_enforces_one_per_order(
        self,
    ) -> None:
        """Reporting a user on an order creates an open UserReport and blocks duplicate for that order."""
        self.client.force_authenticate(user=self.borrower)
        resp1 = self.client.post(
            "/api/v1/reports/users/",
            {
                "target_user_id": self.lender.pk,
                "order_id": self.order1.pk,
                "category": "scam_fraud",
                "description": "Requested suspicious deposit.",
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp1.data["status"], "open")
        self.assertEqual(resp1.data["order_id"], self.order1.pk)

        # Duplicate report on the same order is rejected
        dup_resp = self.client.post(
            "/api/v1/reports/users/",
            {
                "target_user_id": self.lender.pk,
                "order_id": self.order1.pk,
                "category": "harassment",
                "description": "Second report on same order.",
            },
            format="json",
        )
        self.assertEqual(dup_resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Reporting the same user on a different order (order2) is allowed
        resp2 = self.client.post(
            f"/api/v1/users/{self.lender.pk}/report/",
            {
                "order_id": self.order2.pk,
                "category": "harassment",
                "description": "Separate incident on second order.",
            },
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UserReport.objects.filter(target_user=self.lender).count(), 2)

    def test_submit_listing_review_and_message_reports_enforce_uniqueness(self) -> None:
        """Listing, review, and message reports create Open entries and reject duplicates."""
        self.client.force_authenticate(user=self.borrower)

        # 1. Listing report
        l_resp = self.client.post(
            "/api/v1/reports/",
            {
                "target_type": "listing",
                "target_id": self.listing.pk,
                "category": "misleading_description",
                "description": "Photos do not match actual edition.",
            },
            format="json",
        )
        self.assertEqual(l_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(l_resp.data["status"], "open")
        self.assertEqual(ListingReport.objects.count(), 1)

        l_dup = self.client.post(
            f"/api/v1/listings/{self.listing.pk}/report/",
            {"category": "prohibited", "description": "Duplicate listing report"},
            format="json",
        )
        self.assertEqual(l_dup.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Message report
        m_resp = self.client.post(
            f"/api/v1/messages/{self.message.pk}/report/",
            {"category": "scam_fraud", "description": "Suspicious message"},
            format="json",
        )
        self.assertEqual(m_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(m_resp.data["status"], "open")
        self.assertEqual(MessageReport.objects.count(), 1)

        m_dup = self.client.post(
            f"/api/v1/messages/{self.message.pk}/report/",
            {"category": "spam", "description": "Duplicate message report"},
            format="json",
        )
        self.assertEqual(m_dup.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Review report (by lender against borrower's review)
        self.client.force_authenticate(user=self.lender)
        r_resp = self.client.post(
            "/api/v1/reports/reviews/",
            {
                "target_review_id": self.review.pk,
                "category": "fake_review",
                "description": "False claim about torn pages.",
            },
            format="json",
        )
        self.assertEqual(r_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r_resp.data["status"], "open")
        self.assertEqual(ReviewReport.objects.count(), 1)

        r_dup = self.client.post(
            f"/api/v1/reviews/{self.review.pk}/report/",
            {"category": "spam", "description": "Duplicate review report"},
            format="json",
        )
        self.assertEqual(r_dup.status_code, status.HTTP_400_BAD_REQUEST)

    def test_self_reporting_and_outsider_message_reporting_are_blocked(self) -> None:
        """Users cannot report their own user/listing/review/message; outsiders get 404 on messages."""
        self.client.force_authenticate(user=self.lender)

        self.assertEqual(
            self.client.post(
                f"/api/v1/users/{self.lender.pk}/report/",
                {"category": "spam", "description": "Self report"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/listings/{self.listing.pk}/report/",
                {"category": "spam", "description": "Own listing"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/messages/{self.message.pk}/report/",
                {"category": "spam", "description": "Own message"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.client.force_authenticate(user=self.borrower)
        self.assertEqual(
            self.client.post(
                f"/api/v1/reviews/{self.review.pk}/report/",
                {"category": "spam", "description": "Own review"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        # Outsider attempting to report a private chat message gets 404 Not Found
        self.client.force_authenticate(user=self.outsider)
        outsider_msg = self.client.post(
            f"/api/v1/messages/{self.message.pk}/report/",
            {"category": "spam", "description": "Snooping"},
            format="json",
        )
        self.assertEqual(outsider_msg.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(CRON_SECRET_TOKEN="test-cron-secret-902")
class AutoFlagRepeatedlyReportedUsersTests(TestCase):
    """Test suite for CP-902 rolling 30-day auto-flagging and admin flag confirmation."""

    def setUp(self) -> None:
        self.client = APIClient()

        self.admin = User.objects.create_user(
            email="admin_cp902@pup.edu.ph",
            password="StrongPassword123!",
            full_name="Admin CP902",
            contact_number="09170000902",
            affiliation=User.AffiliationChoices.STAFF,
            account_status=User.AccountStatusChoices.ACTIVE,
            is_staff=True,
            email_verified_at=timezone.now(),
        )
        self.target = User.objects.create_user(
            email="target_cp902@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Target User CP902",
            contact_number="09171110902",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.other_lender = User.objects.create_user(
            email="other_lender_cp902@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Other Lender CP902",
            contact_number="09172220902",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )

        # Give target a verified identity document so they can borrow
        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        doc_approved, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        IdentityDocument.objects.create(
            user=self.target,
            document_type=doc_type,
            id_number="2023-00902-MN-0",
            document_data=b"fake-id-bytes",
            status=doc_approved,
            name_on_document=self.target.full_name,
            consent_given=True,
            consented_at=timezone.now(),
        )

        self.reporters = [
            User.objects.create_user(
                email=f"reporter{i}_cp902@iskolarngbayan.pup.edu.ph",
                password="StrongPassword123!",
                full_name=f"Reporter {i}",
                contact_number=f"0917902000{i}",
                affiliation=User.AffiliationChoices.STUDENT,
                account_status=User.AccountStatusChoices.ACTIVE,
                email_verified_at=timezone.now(),
            )
            for i in range(1, 5)
        ]

        self.category, _ = ListingCategory.objects.get_or_create(name="Lab Gear")
        self.pickup_location, _ = PickupLocation.objects.get_or_create(
            name="Pylon",
            defaults={"description": "Main Gate"},
        )
        self.listing_active, _ = ListingStatus.objects.get_or_create(name="active")
        self.other_listing = Listing.objects.create(
            lender=self.other_lender,
            category=self.category,
            pickup_location=self.pickup_location,
            status=self.listing_active,
            title="Digital Multimeter",
            description="Working multimeter",
            condition="good",
            rate_per_day=Decimal("20.00"),
            is_ownership_confirmed=True,
        )
        AvailabilityWindow.objects.create(
            listing=self.other_listing,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
        )

        self.report_cat, _ = UserReportCategory.objects.get_or_create(name="scam_fraud")

    def test_auto_flag_job_requires_cron_secret_and_respects_rolling_30_days(
        self,
    ) -> None:
        """Auto-flag job requires CRON_SECRET_TOKEN and only counts reports within rolling 30 days."""
        unauth = self.client.post("/api/v1/jobs/auto-flag-users/")
        self.assertEqual(unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # Create 2 recent reports and 1 report from 35 days ago (outside 30-day window)
        UserReport.objects.create(
            reporter=self.reporters[0],
            target_user=self.target,
            category=self.report_cat,
            description="Recent report 1",
        )
        UserReport.objects.create(
            reporter=self.reporters[1],
            target_user=self.target,
            category=self.report_cat,
            description="Recent report 2",
        )
        r_old = UserReport.objects.create(
            reporter=self.reporters[2],
            target_user=self.target,
            category=self.report_cat,
            description="Old report outside 30-day window",
        )
        UserReport.objects.filter(pk=r_old.pk).update(
            created_at=timezone.now() - timedelta(days=35)
        )

        resp_below = self.client.post(
            "/api/v1/jobs/auto-flag-users/",
            HTTP_AUTHORIZATION="Bearer test-cron-secret-902",
        )
        self.assertEqual(resp_below.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_below.data["flagged_count"], 0)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_flagged)

        # Add a 3rd report within the rolling 30-day window
        UserReport.objects.create(
            reporter=self.reporters[3],
            target_user=self.target,
            category=self.report_cat,
            description="Recent report 3",
        )
        resp_flag = self.client.post(
            "/api/v1/jobs/auto-flag-users/",
            HTTP_AUTHORIZATION="Bearer test-cron-secret-902",
        )
        self.assertEqual(resp_flag.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_flag.data["flagged_count"], 1)
        self.assertIn(self.target.pk, resp_flag.data["flagged_user_ids"])

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_flagged)
        self.assertFalse(self.target.is_flag_confirmed)
        self.assertEqual(self.target.account_status, User.AccountStatusChoices.ACTIVE)

    def test_unconfirmed_flag_leaves_account_unrestricted_until_admin_confirms(
        self,
    ) -> None:
        """
        CP-902:
        1. Auto-flagged user (is_flagged=True, is_flag_confirmed=False) remains unrestricted
           and can create listings and borrow requests.
        2. After Admin confirms flag (is_flag_confirmed=True), listing and borrow request
           creation are blocked.
        3. Dismissing the flag restores listing and borrow request creation.
        """
        for i in range(3):
            UserReport.objects.create(
                reporter=self.reporters[i],
                target_user=self.target,
                category=self.report_cat,
                description=f"Report {i + 1}",
            )

        self.client.post(
            "/api/v1/jobs/auto-flag-users/",
            HTTP_AUTHORIZATION="Bearer test-cron-secret-902",
        )
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_flagged)
        self.assertFalse(self.target.is_flag_confirmed)

        # 1. Unconfirmed flag: target CAN still create a listing and a borrow request
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01"
            b"\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        photo = SimpleUploadedFile("item.png", png_bytes, content_type="image/png")
        today = timezone.localdate()

        created_listing = create_listing(
            lender=self.target,
            title="Unrestricted Listing",
            description="Created while unconfirmed flag is active",
            category=self.category,
            condition="good",
            pickup_location=self.pickup_location,
            rate_per_day=Decimal("10.00"),
            is_ownership_confirmed=True,
            photos=[photo],
            availability_windows=[
                {"start_date": today, "end_date": today + timedelta(days=5)}
            ],
        )
        self.assertIsNotNone(created_listing.pk)

        created_order = request_borrow(
            borrower=self.target,
            listing_id=self.other_listing.pk,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=2),
        )
        self.assertIsNotNone(created_order.pk)

        # 2. Admin confirms the flag
        self.client.force_authenticate(user=self.admin)
        confirm_resp = self.client.post(
            f"/api/v1/admin/users/{self.target.pk}/confirm-flag/",
            {"reason": "Confirmed repeated scam reports"},
            format="json",
        )
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(confirm_resp.data["is_flagged"])
        self.assertTrue(confirm_resp.data["is_flag_confirmed"])

        self.target.refresh_from_db()
        self.assertTrue(self.target.is_flag_confirmed)

        # Now target is blocked from creating new listings (API & service)
        self.client.force_authenticate(user=self.target)
        blocked_listing_resp = self.client.post(
            "/api/v1/listings/",
            {"title": "Blocked Listing"},
            format="json",
        )
        self.assertEqual(blocked_listing_resp.status_code, status.HTTP_403_FORBIDDEN)

        with self.assertRaises(ValidationError):
            create_listing(
                lender=self.target,
                title="Blocked Service Listing",
                description="Should fail",
                category=self.category,
                condition="good",
                pickup_location=self.pickup_location,
                rate_per_day=Decimal("10.00"),
                is_ownership_confirmed=True,
                photos=[],
                availability_windows=[],
            )

        # And blocked from creating new borrow requests
        blocked_borrow_resp = self.client.post(
            "/api/v1/orders/",
            {
                "listing_id": self.other_listing.pk,
                "start_date": str(today + timedelta(days=5)),
                "end_date": str(today + timedelta(days=6)),
            },
            format="json",
        )
        self.assertEqual(blocked_borrow_resp.status_code, status.HTTP_403_FORBIDDEN)

        with self.assertRaises(PermissionDenied):
            request_borrow(
                borrower=self.target,
                listing_id=self.other_listing.pk,
                start_date=today + timedelta(days=7),
                end_date=today + timedelta(days=8),
            )

        # 3. Admin dismisses the flag -> restrictions lifted
        self.client.force_authenticate(user=self.admin)
        dismiss_resp = self.client.post(
            f"/api/v1/admin/users/{self.target.pk}/dismiss-flag/",
            {"reason": "Cleared after investigation"},
            format="json",
        )
        self.assertEqual(dismiss_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(dismiss_resp.data["is_flagged"])
        self.assertFalse(dismiss_resp.data["is_flag_confirmed"])

        self.target.refresh_from_db()
        restored_order = request_borrow(
            borrower=self.target,
            listing_id=self.other_listing.pk,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=11),
        )
        self.assertIsNotNone(restored_order.pk)
