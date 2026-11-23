"""Automated unit and integration tests for CP-506 (Overdue orders, Unreturned escalation, Admin review cases & status overrides)."""

from __future__ import annotations

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.audit.models import AdminAccessLog
from apps.chat.models import Conversation, Message
from apps.codes.constants import CODE_STATUS_ACTIVE, CODE_TYPE_HANDOVER
from apps.codes.models import AuthCode, AuthCodeAttempt, AuthCodeStatus, AuthCodeType
from apps.core.constants import UNRETURNED_ESCALATION_DAYS
from apps.core.models import SystemConfig
from apps.listings.models import (
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.listings.services import block_dates_for_order
from apps.notifications.constants import (
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_UNRETURNED_STATUS,
)
from apps.notifications.models import Notification
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)

from .constants import (
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_RETURNED,
    ORDER_STATUS_UNRETURNED,
    UNRETURNED_CASE_STATUS_ESCALATED,
    UNRETURNED_CASE_STATUS_OPEN,
    UNRETURNED_CASE_STATUS_RETURNED,
    UNRETURNED_CASE_STATUS_UNRESOLVED,
)
from .models import (
    Dispute,
    DisputeEvidence,
    Order,
    OrderStatus,
    OrderStatusOverride,
    UnreturnedCase,
    UnreturnedCaseStatus,
)


class OverdueAndUnreturnedCaseTests(APITestCase):
    """Tests covering all CP-506 checklist requirements."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            email="admin@pup.edu.ph",
            password="AdminPassword123!",
            full_name="PUP Admin",
            contact_number="09170000001",
        )
        self.lender = User.objects.create_user(
            email="lender.cp506@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender CP506",
            contact_number="09171112222",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.borrower = User.objects.create_user(
            email="borrower.cp506@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower CP506",
            contact_number="09181112222",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            street_address="123 Anonas St",
            email_verified_at=timezone.now(),
        )

        # Borrower approved identity document for dossier linking test
        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        doc_status, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        self.borrower_doc = IdentityDocument.objects.create(
            user=self.borrower,
            document_type=doc_type,
            id_number="2023-12345-MN-0",
            document_data=b"encrypted-id-bytes",
            status=doc_status,
            name_on_document="Borrower CP506",
            consent_given=True,
            consented_at=timezone.now(),
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Lab Equipment")
        self.location, _ = PickupLocation.objects.get_or_create(
            name="Engineering Lab",
            defaults={"description": "Room 301"},
        )
        self.active_listing_status, _ = ListingStatus.objects.get_or_create(
            name="active"
        )
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Digital Multimeter Fluke 117",
            description="Precision digital multimeter.",
            category=self.category,
            condition="good",
            pickup_location=self.location,
            rate_per_day=None,
            is_ownership_confirmed=True,
            status=self.active_listing_status,
        )

        self.active_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_ACTIVE
        )
        self.overdue_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_OVERDUE
        )
        self.unreturned_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_UNRETURNED
        )

    @override_settings(CRON_SECRET_TOKEN="test-cron-secret")
    def test_cron_job_auth_and_auto_overdue_transition_notifies_both_parties(
        self,
    ) -> None:
        """CP-506: Cron job rejects unauthorized calls; marks Active orders past end_date as Overdue and notifies both parties."""
        today = timezone.localdate()
        overdue_candidate = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=4),
            end_date=today - timedelta(days=1),
            status=self.active_status,
        )
        still_current = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=2),
            status=self.active_status,
        )

        url = reverse("job-check-overdue")

        # Missing secret -> 401
        unauth_res = self.client.post(url)
        self.assertEqual(unauth_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Valid secret -> 200
        res = self.client.post(url, HTTP_AUTHORIZATION="Bearer test-cron-secret")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.json()
        self.assertEqual(body["overdue_count"], 1)
        self.assertEqual(body["overdue_order_ids"], [overdue_candidate.pk])

        overdue_candidate.refresh_from_db()
        still_current.refresh_from_db()
        self.assertEqual(overdue_candidate.status.name, ORDER_STATUS_OVERDUE)
        self.assertEqual(still_current.status.name, ORDER_STATUS_ACTIVE)

        # Both Borrower and Lender notified
        self.assertTrue(
            Notification.objects.filter(
                user=self.borrower,
                type__name=NOTIFICATION_TYPE_OVERDUE_STATUS,
                reference_id=str(overdue_candidate.pk),
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_OVERDUE_STATUS,
                reference_id=str(overdue_candidate.pk),
            ).exists()
        )

    @override_settings(CRON_SECRET_TOKEN="test-cron-secret")
    def test_auto_set_unreturned_after_7_days_overdue_suspends_borrower_and_opens_case(
        self,
    ) -> None:
        """CP-506: Auto-sets Unreturned after 7 days Overdue (configurable), auto-suspends Borrower, and opens UnreturnedCase."""
        today = timezone.localdate()
        seven_days_overdue_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=7),
            status=self.overdue_status,
        )
        two_days_overdue_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=2),
            status=self.overdue_status,
        )

        url = reverse("job-check-overdue")
        res = self.client.post(url, HTTP_AUTHORIZATION="Bearer test-cron-secret")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["unreturned_count"], 1)
        self.assertEqual(data["unreturned_order_ids"], [seven_days_overdue_order.pk])

        seven_days_overdue_order.refresh_from_db()
        two_days_overdue_order.refresh_from_db()
        self.borrower.refresh_from_db()

        self.assertEqual(seven_days_overdue_order.status.name, ORDER_STATUS_UNRETURNED)
        self.assertEqual(two_days_overdue_order.status.name, ORDER_STATUS_OVERDUE)
        self.assertEqual(
            self.borrower.account_status, User.AccountStatusChoices.SUSPENDED
        )

        case = UnreturnedCase.objects.get(order=seven_days_overdue_order)
        self.assertEqual(case.status.name, UNRETURNED_CASE_STATUS_OPEN)

        # Both parties notified of unreturned status
        self.assertTrue(
            Notification.objects.filter(
                user=self.borrower,
                type__name=NOTIFICATION_TYPE_UNRETURNED_STATUS,
                reference_id=str(seven_days_overdue_order.pk),
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_UNRETURNED_STATUS,
                reference_id=str(seven_days_overdue_order.pk),
            ).exists()
        )

    @override_settings(CRON_SECRET_TOKEN="test-cron-secret")
    def test_unreturned_escalation_respects_system_config_days(self) -> None:
        """CP-506: UNRETURNED_ESCALATION_DAYS in SystemConfig overrides the 7-day default."""
        SystemConfig.objects.create(
            config_key=UNRETURNED_ESCALATION_DAYS,
            config_value="3",
        )
        today = timezone.localdate()
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=6),
            end_date=today - timedelta(days=3),
            status=self.overdue_status,
        )

        url = reverse("job-check-overdue")
        res = self.client.post(url, HTTP_AUTHORIZATION="Bearer test-cron-secret")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status.name, ORDER_STATUS_UNRETURNED)

    def test_admin_review_case_dossier_links_identity_contact_order_chat_and_code_data(
        self,
    ) -> None:
        """CP-506: Admin review case detail links identity, contact, order, chat messages, and code attempts + logs AdminAccessLog."""
        today = timezone.localdate()
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=8),
            status=self.unreturned_status,
        )
        open_status, _ = UnreturnedCaseStatus.objects.get_or_create(
            name=UNRETURNED_CASE_STATUS_OPEN
        )
        case = UnreturnedCase.objects.create(order=order, status=open_status)

        # Link a chat conversation and message
        conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.lender,
            listing=self.listing,
            order=order,
        )
        Message.objects.create(
            conversation=conv,
            sender=self.lender,
            content="Please return the multimeter today.",
        )

        # Link an auth code and attempt
        handover_type, _ = AuthCodeType.objects.get_or_create(name=CODE_TYPE_HANDOVER)
        active_code_status, _ = AuthCodeStatus.objects.get_or_create(
            name=CODE_STATUS_ACTIVE
        )
        code = AuthCode.objects.create(
            order=order,
            code_type=handover_type,
            code_value="654321",
            expires_at=timezone.now() + timedelta(hours=3),
            auth_status=active_code_status,
        )
        AuthCodeAttempt.objects.create(
            code=code,
            attempted_by=self.borrower,
            was_successful=True,
        )

        # Non-admin is forbidden
        self.client.force_authenticate(user=self.lender)
        forbidden_res = self.client.get(
            reverse("unreturned-case-detail", kwargs={"pk": case.pk})
        )
        self.assertEqual(forbidden_res.status_code, status.HTTP_403_FORBIDDEN)

        # Admin fetches full dossier
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(reverse("unreturned-case-detail", kwargs={"pk": case.pk}))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        dossier = res.json()

        self.assertEqual(dossier["id"], case.pk)
        self.assertEqual(dossier["status"], UNRETURNED_CASE_STATUS_OPEN)
        self.assertEqual(dossier["order"]["id"], order.pk)
        self.assertEqual(dossier["borrower"]["email"], self.borrower.email)
        self.assertEqual(
            dossier["borrower"]["contact_number"], self.borrower.contact_number
        )
        self.assertEqual(len(dossier["borrower"]["identity_documents"]), 1)
        self.assertEqual(
            dossier["borrower"]["identity_documents"][0]["id_number"],
            "2023-12345-MN-0",
        )
        self.assertEqual(len(dossier["chat"]), 1)
        self.assertEqual(
            dossier["chat"][0]["messages"][0]["content"],
            "Please return the multimeter today.",
        )
        self.assertEqual(len(dossier["codes"]), 1)
        self.assertEqual(dossier["codes"][0]["code_value"], "654321")
        self.assertEqual(len(dossier["codes"][0]["attempts"]), 1)

        # Verify AdminAccessLog recorded contact_release on borrower's identity document
        self.assertTrue(
            AdminAccessLog.objects.filter(
                document=self.borrower_doc,
                admin=self.admin,
                action="contact_release",
            ).exists()
        )

    def test_admin_escalates_case_to_oss_campus_security_with_attached_evidence(
        self,
    ) -> None:
        """CP-506: Admin can escalate an UnreturnedCase to OSS/Campus Security with attached evidence and notes."""
        today = timezone.localdate()
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=8),
            status=self.unreturned_status,
        )
        open_status, _ = UnreturnedCaseStatus.objects.get_or_create(
            name=UNRETURNED_CASE_STATUS_OPEN
        )
        case = UnreturnedCase.objects.create(order=order, status=open_status)

        evidence_file = SimpleUploadedFile(
            "oss_report.jpg",
            b"fake-image-evidence",
            content_type="image/jpeg",
        )

        self.client.force_authenticate(user=self.admin)
        url = reverse("unreturned-case-escalate", kwargs={"pk": case.pk})
        res = self.client.post(
            url,
            {
                "resolution_notes": "Escalated to PUP OSS and Campus Security with chat & ID log.",
                "evidence": evidence_file,
            },
            format="multipart",
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], UNRETURNED_CASE_STATUS_ESCALATED)
        self.assertEqual(data["escalated_by_id"], self.admin.pk)
        self.assertIsNotNone(data["escalated_at"])
        self.assertEqual(
            data["resolution_notes"],
            "Escalated to PUP OSS and Campus Security with chat & ID log.",
        )
        self.assertEqual(len(data["evidences"]), 1)
        self.assertEqual(
            DisputeEvidence.objects.filter(dispute__order=order).count(), 1
        )
        self.assertTrue(
            Dispute.objects.filter(
                order=order, status=Dispute.StatusChoices.ESCALATED
            ).exists()
        )

    def test_admin_closes_case_as_returned_or_unresolved(self) -> None:
        """CP-506: Admin can close an UnreturnedCase as Returned (updating order & reinstating borrower) or Unresolved."""
        today = timezone.localdate()
        self.borrower.account_status = User.AccountStatusChoices.SUSPENDED
        self.borrower.save(update_fields=["account_status"])

        order1 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=12),
            end_date=today - timedelta(days=9),
            status=self.unreturned_status,
        )
        block_dates_for_order(order1)
        open_status, _ = UnreturnedCaseStatus.objects.get_or_create(
            name=UNRETURNED_CASE_STATUS_OPEN
        )
        case1 = UnreturnedCase.objects.create(order=order1, status=open_status)

        self.client.force_authenticate(user=self.admin)
        close_url1 = reverse("unreturned-case-close", kwargs={"pk": case1.pk})
        res1 = self.client.post(
            close_url1,
            {
                "status": UNRETURNED_CASE_STATUS_RETURNED,
                "resolution_notes": "Item physically surrendered at OSS office.",
            },
            format="json",
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.json()["status"], UNRETURNED_CASE_STATUS_RETURNED)

        order1.refresh_from_db()
        self.borrower.refresh_from_db()
        self.assertEqual(order1.status.name, ORDER_STATUS_RETURNED)
        self.assertEqual(self.borrower.account_status, User.AccountStatusChoices.ACTIVE)
        self.assertFalse(BlockedDateRange.objects.filter(order=order1).exists())
        self.assertTrue(
            OrderStatusOverride.objects.filter(
                order=order1, new_status=ORDER_STATUS_RETURNED
            ).exists()
        )

        # Closing a second case as Unresolved keeps borrower suspended and order unreturned
        self.borrower.account_status = User.AccountStatusChoices.SUSPENDED
        self.borrower.save(update_fields=["account_status"])
        order2 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today - timedelta(days=15),
            end_date=today - timedelta(days=10),
            status=self.unreturned_status,
        )
        case2 = UnreturnedCase.objects.create(order=order2, status=open_status)
        close_url2 = reverse("unreturned-case-close", kwargs={"pk": case2.pk})
        res2 = self.client.post(
            close_url2,
            {
                "status": UNRETURNED_CASE_STATUS_UNRESOLVED,
                "resolution_notes": "Borrower unreachable after security escalation.",
            },
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.json()["status"], UNRETURNED_CASE_STATUS_UNRESOLVED)
        order2.refresh_from_db()
        self.borrower.refresh_from_db()
        self.assertEqual(order2.status.name, ORDER_STATUS_UNRETURNED)
        self.assertEqual(
            self.borrower.account_status, User.AccountStatusChoices.SUSPENDED
        )

    def test_admin_manual_status_correction_with_recorded_reason(self) -> None:
        """CP-506: Admin can manually override order status with a recorded reason in OrderStatusOverride."""
        today = timezone.localdate()
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today,
            end_date=today + timedelta(days=2),
            status=self.active_status,
        )
        block_dates_for_order(order)

        url = reverse("order-override-status", kwargs={"pk": order.pk})

        # Non-admin rejected
        self.client.force_authenticate(user=self.lender)
        self.assertEqual(
            self.client.post(
                url,
                {"new_status": ORDER_STATUS_COMPLETED, "reason": "Try override"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Blank reason rejected with 400
        self.client.force_authenticate(user=self.admin)
        bad_res = self.client.post(
            url,
            {"new_status": ORDER_STATUS_COMPLETED, "reason": "   "},
            format="json",
        )
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Valid override -> 200 + OrderStatusOverride created + calendar dates released
        ok_res = self.client.post(
            url,
            {
                "new_status": ORDER_STATUS_COMPLETED,
                "reason": "Both parties confirmed offline return during power outage.",
            },
            format="json",
        )
        self.assertEqual(ok_res.status_code, status.HTTP_200_OK)
        body = ok_res.json()
        self.assertEqual(body["status"], ORDER_STATUS_COMPLETED)
        self.assertEqual(body["override"]["previous_status"], ORDER_STATUS_ACTIVE)
        self.assertEqual(body["override"]["new_status"], ORDER_STATUS_COMPLETED)
        self.assertEqual(
            body["override"]["reason"],
            "Both parties confirmed offline return during power outage.",
        )

        order.refresh_from_db()
        self.assertEqual(order.status.name, ORDER_STATUS_COMPLETED)
        self.assertFalse(BlockedDateRange.objects.filter(order=order).exists())
