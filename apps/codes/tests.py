"""Automated unit and integration tests for CP-504 (Handover Code) and CP-505 (Return Code)."""

from __future__ import annotations

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.constants import (
    AUTH_CODE_EXPIRY_HOURS,
    AUTH_CODE_LOCKOUT_MINUTES,
    AUTH_CODE_LOCKOUT_THRESHOLD,
)
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
    NOTIFICATION_TYPE_CODE_GENERATION,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
    NOTIFICATION_TYPE_CONFIRMED_RETURN,
)
from apps.notifications.models import Notification
from apps.orders.constants import (
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_DISPUTED,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_REQUESTED,
)
from apps.orders.models import Dispute, DisputeEvidence, Order, OrderStatus
from apps.users.models import User

from .constants import (
    CODE_STATUS_ACTIVE,
    CODE_STATUS_EXPIRED,
    CODE_STATUS_USED,
    CODE_TYPE_HANDOVER,
    CODE_TYPE_RETURN,
)
from .models import AuthCode, AuthCodeAttempt


class HandoverCodeTests(APITestCase):
    """Tests covering all CP-504 checklist criteria (Handover OTP generation & validation)."""

    def setUp(self) -> None:
        self.lender = User.objects.create_user(
            email="lender@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Student",
            contact_number="09171234567",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.borrower = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Student",
            contact_number="09181234567",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.outsider = User.objects.create_user(
            email="outsider@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Outsider Student",
            contact_number="09191234567",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Electronics")
        self.location, _ = PickupLocation.objects.get_or_create(
            name="Main Library",
            defaults={"description": "Ground Floor Lobby"},
        )
        self.active_listing_status, _ = ListingStatus.objects.get_or_create(
            name="active"
        )
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Scientific Calculator FX-991EX",
            description="Casio scientific calculator in great condition.",
            category=self.category,
            condition="good",
            pickup_location=self.location,
            rate_per_day=None,
            is_ownership_confirmed=True,
            status=self.active_listing_status,
        )

        self.confirmed_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_CONFIRMED
        )
        self.requested_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_REQUESTED
        )
        self.active_order_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_ACTIVE
        )

        today = timezone.localdate()
        self.order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today,
            end_date=today + timedelta(days=3),
            status=self.confirmed_status,
        )

    def _generate_url(self, order_id: int | None = None) -> str:
        return reverse(
            "order-handover-code-generate",
            kwargs={"order_id": order_id or self.order.pk},
        )

    def _verify_url(self, order_id: int | None = None) -> str:
        return reverse(
            "order-handover-code-verify",
            kwargs={"order_id": order_id or self.order.pk},
        )

    def test_lender_generates_handover_code_on_confirmed_order(self) -> None:
        """CP-504: Lender can generate a 6-digit handover code on a Confirmed order."""
        self.client.force_authenticate(user=self.lender)
        before = timezone.now()
        response = self.client.post(self._generate_url())
        after = timezone.now()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["order_id"], self.order.pk)
        self.assertEqual(data["code_type"], CODE_TYPE_HANDOVER)
        self.assertEqual(data["auth_status"], CODE_STATUS_ACTIVE)
        self.assertRegex(data["code_value"], r"^\d{6}$")

        auth_code = AuthCode.objects.get(pk=data["id"])
        self.assertGreaterEqual(
            auth_code.expires_at, before + timedelta(hours=3) - timedelta(seconds=1)
        )
        self.assertLessEqual(
            auth_code.expires_at, after + timedelta(hours=3) + timedelta(seconds=1)
        )

        self.assertTrue(
            Notification.objects.filter(
                user=self.borrower,
                type__name=NOTIFICATION_TYPE_CODE_GENERATION,
                reference_id=str(self.order.pk),
            ).exists()
        )

    def test_generate_handover_code_respects_system_config_expiry_hours(self) -> None:
        """CP-504: Code expiry defaults to 3h and honors SystemConfig override."""
        SystemConfig.objects.create(
            config_key=AUTH_CODE_EXPIRY_HOURS,
            config_value="5",
        )
        self.client.force_authenticate(user=self.lender)
        before = timezone.now()
        response = self.client.post(self._generate_url())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        auth_code = AuthCode.objects.get(pk=response.json()["id"])
        self.assertGreaterEqual(
            auth_code.expires_at, before + timedelta(hours=5) - timedelta(seconds=2)
        )

    def test_regenerating_handover_code_expires_previous_active_code(self) -> None:
        """CP-504: Generating a new handover code supersedes any prior active handover code."""
        self.client.force_authenticate(user=self.lender)
        first_res = self.client.post(self._generate_url())
        second_res = self.client.post(self._generate_url())

        first_code = AuthCode.objects.get(pk=first_res.json()["id"])
        second_code = AuthCode.objects.get(pk=second_res.json()["id"])

        self.assertEqual(first_code.auth_status.name, CODE_STATUS_EXPIRED)
        self.assertEqual(second_code.auth_status.name, CODE_STATUS_ACTIVE)

    def test_only_lender_can_generate_handover_code_and_only_when_confirmed(
        self,
    ) -> None:
        """CP-504: Borrower/outsider cannot generate handover code; non-Confirmed orders return 409."""
        self.client.force_authenticate(user=self.borrower)
        res_borrower = self.client.post(self._generate_url())
        self.assertEqual(res_borrower.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.outsider)
        res_outsider = self.client.post(self._generate_url())
        self.assertEqual(res_outsider.status_code, status.HTTP_403_FORBIDDEN)

        self.order.status = self.requested_status
        self.order.save(update_fields=["status"])
        self.client.force_authenticate(user=self.lender)
        res_state = self.client.post(self._generate_url())
        self.assertEqual(res_state.status_code, status.HTTP_409_CONFLICT)

    def test_borrower_validates_handover_code_sets_order_active_and_logs_attempt(
        self,
    ) -> None:
        """CP-504: Validating handover code sets order Active, blocks dates, marks code used, and logs attempt."""
        self.client.force_authenticate(user=self.lender)
        gen_res = self.client.post(self._generate_url())
        code_value = gen_res.json()["code_value"]
        code_id = gen_res.json()["id"]

        self.client.force_authenticate(user=self.borrower)
        verify_res = self.client.post(
            self._verify_url(),
            {"code": code_value},
            format="json",
        )

        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        body = verify_res.json()
        self.assertEqual(body["status"], ORDER_STATUS_ACTIVE)
        self.assertEqual(body["auth_code"]["auth_status"], CODE_STATUS_USED)
        self.assertIsNotNone(body["auth_code"]["used_at"])

        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, ORDER_STATUS_ACTIVE)
        self.assertTrue(BlockedDateRange.objects.filter(order=self.order).exists())

        attempt = AuthCodeAttempt.objects.get(code_id=code_id)
        self.assertTrue(attempt.was_successful)
        self.assertEqual(attempt.attempted_by, self.borrower)

        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
                reference_id=str(self.order.pk),
            ).exists()
        )

    def test_reject_incorrect_expired_and_used_handover_codes(self) -> None:
        """CP-504: Rejects wrong, expired, and already-used codes with 400 and logs failed attempts."""
        self.client.force_authenticate(user=self.lender)
        gen_res = self.client.post(self._generate_url())
        code_id = gen_res.json()["id"]
        code_value = gen_res.json()["code_value"]
        wrong_code = "000000" if code_value != "000000" else "999999"

        # 1. Wrong code -> 400 + failed attempt logged
        self.client.force_authenticate(user=self.borrower)
        wrong_res = self.client.post(
            self._verify_url(), {"code": wrong_code}, format="json"
        )
        self.assertEqual(wrong_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            AuthCodeAttempt.objects.filter(
                code_id=code_id, was_successful=False
            ).count(),
            1,
        )

        # 2. Expired code -> 400 + code status flipped to expired + failed attempt logged
        AuthCode.objects.filter(pk=code_id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        expired_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(expired_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            AuthCode.objects.get(pk=code_id).auth_status.name, CODE_STATUS_EXPIRED
        )
        self.assertEqual(
            AuthCodeAttempt.objects.filter(
                code_id=code_id, was_successful=False
            ).count(),
            2,
        )

        # 3. Used code -> 400 + failed attempt logged even after order became Active
        self.client.force_authenticate(user=self.lender)
        fresh_res = self.client.post(self._generate_url())
        fresh_code = fresh_res.json()["code_value"]
        fresh_id = fresh_res.json()["id"]

        self.client.force_authenticate(user=self.borrower)
        ok_res = self.client.post(
            self._verify_url(), {"code": fresh_code}, format="json"
        )
        self.assertEqual(ok_res.status_code, status.HTTP_200_OK)

        reuse_res = self.client.post(
            self._verify_url(), {"code": fresh_code}, format="json"
        )
        self.assertEqual(reuse_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been used", str(reuse_res.json()))
        self.assertEqual(
            AuthCodeAttempt.objects.filter(
                code_id=fresh_id, was_successful=False
            ).count(),
            1,
        )

    def test_lockout_after_repeated_failed_attempts_and_unlock_after_window(
        self,
    ) -> None:
        """CP-504: Locks code verification after N consecutive failed attempts and unlocks when lockout expires."""
        SystemConfig.objects.create(
            config_key=AUTH_CODE_LOCKOUT_THRESHOLD,
            config_value="3",
        )
        SystemConfig.objects.create(
            config_key=AUTH_CODE_LOCKOUT_MINUTES,
            config_value="10",
        )

        self.client.force_authenticate(user=self.lender)
        gen_res = self.client.post(self._generate_url())
        code_value = gen_res.json()["code_value"]
        wrong_code = "111111" if code_value != "111111" else "222222"

        self.client.force_authenticate(user=self.borrower)
        for _ in range(3):
            res = self.client.post(
                self._verify_url(), {"code": wrong_code}, format="json"
            )
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 4th attempt (even with the RIGHT code) is rejected with 429 while locked out
        locked_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(locked_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("locked_until", locked_res.json())

        # Once lockout window passes, borrower can verify the valid code
        past_time = timezone.now() - timedelta(minutes=11)
        AuthCodeAttempt.objects.filter(attempted_by=self.borrower).update(
            attempted_at=past_time
        )

        unlocked_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(unlocked_res.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, ORDER_STATUS_ACTIVE)


class ReturnCodeTests(APITestCase):
    """Tests covering all CP-505 checklist criteria (Return OTP generation & validation)."""

    def setUp(self) -> None:
        self.lender = User.objects.create_user(
            email="lender.return@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Return",
            contact_number="09171234568",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.borrower = User.objects.create_user(
            email="borrower.return@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Return",
            contact_number="09181234568",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Books")
        self.location, _ = PickupLocation.objects.get_or_create(
            name="CEA Building Lobby",
            defaults={"description": "Main Entrance"},
        )
        self.active_listing_status, _ = ListingStatus.objects.get_or_create(
            name="active"
        )
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Engineering Mathematics Textbook",
            description="Complete pages.",
            category=self.category,
            condition="good",
            pickup_location=self.location,
            rate_per_day=None,
            is_ownership_confirmed=True,
            status=self.active_listing_status,
        )

        self.active_order_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_ACTIVE
        )
        self.overdue_order_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_OVERDUE
        )
        self.confirmed_order_status, _ = OrderStatus.objects.get_or_create(
            name=ORDER_STATUS_CONFIRMED
        )

        today = timezone.localdate()
        self.order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=today,
            end_date=today + timedelta(days=2),
            status=self.active_order_status,
        )
        block_dates_for_order(self.order)

    def _generate_url(self, order_id: int | None = None) -> str:
        return reverse(
            "order-return-code-generate",
            kwargs={"order_id": order_id or self.order.pk},
        )

    def _verify_url(self, order_id: int | None = None) -> str:
        return reverse(
            "order-return-code-verify",
            kwargs={"order_id": order_id or self.order.pk},
        )

    def test_borrower_generates_return_code_on_active_or_overdue_order(self) -> None:
        """CP-505: Borrower generates a 6-digit return code on Active or Overdue orders; Lender is notified."""
        self.client.force_authenticate(user=self.borrower)
        res = self.client.post(self._generate_url())
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data["code_type"], CODE_TYPE_RETURN)
        self.assertEqual(data["auth_status"], CODE_STATUS_ACTIVE)
        self.assertRegex(data["code_value"], r"^\d{6}$")

        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_CODE_GENERATION,
                reference_id=str(self.order.pk),
            ).exists()
        )

        # Also works when order is Overdue
        self.order.status = self.overdue_order_status
        self.order.save(update_fields=["status"])
        res_overdue = self.client.post(self._generate_url())
        self.assertEqual(res_overdue.status_code, status.HTTP_201_CREATED)

    def test_only_borrower_can_generate_return_code_and_only_for_active_or_overdue(
        self,
    ) -> None:
        """CP-505: Lender cannot generate return code; Confirmed orders return 409."""
        self.client.force_authenticate(user=self.lender)
        res_lender = self.client.post(self._generate_url())
        self.assertEqual(res_lender.status_code, status.HTTP_403_FORBIDDEN)

        self.order.status = self.confirmed_order_status
        self.order.save(update_fields=["status"])
        self.client.force_authenticate(user=self.borrower)
        res_state = self.client.post(self._generate_url())
        self.assertEqual(res_state.status_code, status.HTTP_409_CONFLICT)

    def test_lender_verifies_return_code_unflagged_sets_returned_then_completed_and_releases_dates(
        self,
    ) -> None:
        """CP-505: Unflagged return code validation sets Returned -> auto-sets Completed, releases dates, and notifies."""
        self.client.force_authenticate(user=self.borrower)
        gen_res = self.client.post(self._generate_url())
        code_value = gen_res.json()["code_value"]
        code_id = gen_res.json()["id"]

        self.client.force_authenticate(user=self.lender)
        verify_res = self.client.post(
            self._verify_url(),
            {"code": code_value, "flagged": False},
            format="json",
        )

        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        body = verify_res.json()
        self.assertEqual(body["returned_status"], "returned")
        self.assertEqual(body["status"], ORDER_STATUS_COMPLETED)
        self.assertIsNone(body["dispute_id"])
        self.assertEqual(body["auth_code"]["auth_status"], CODE_STATUS_USED)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, ORDER_STATUS_COMPLETED)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())

        attempt = AuthCodeAttempt.objects.get(code_id=code_id)
        self.assertTrue(attempt.was_successful)
        self.assertEqual(attempt.attempted_by, self.lender)

        self.assertTrue(
            Notification.objects.filter(
                user=self.borrower,
                type__name=NOTIFICATION_TYPE_CONFIRMED_RETURN,
                reference_id=str(self.order.pk),
            ).exists()
        )

    def test_lender_verifies_return_code_with_damage_flag_sets_disputed_and_creates_dispute(
        self,
    ) -> None:
        """CP-505: Flagged return code validation sets Returned -> auto-sets Disputed and creates Dispute + evidence."""
        self.client.force_authenticate(user=self.borrower)
        gen_res = self.client.post(self._generate_url())
        code_value = gen_res.json()["code_value"]

        evidence_photo = SimpleUploadedFile(
            "damage.jpg",
            b"fake-jpeg-bytes",
            content_type="image/jpeg",
        )

        self.client.force_authenticate(user=self.lender)
        verify_res = self.client.post(
            self._verify_url(),
            {
                "code": code_value,
                "flagged": "true",
                "dispute_description": "Missing battery cover and cracked screen.",
                "evidence": evidence_photo,
            },
            format="multipart",
        )

        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        body = verify_res.json()
        self.assertEqual(body["returned_status"], "returned")
        self.assertEqual(body["status"], ORDER_STATUS_DISPUTED)
        self.assertIsNotNone(body["dispute_id"])

        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, ORDER_STATUS_DISPUTED)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())

        dispute = Dispute.objects.get(pk=body["dispute_id"])
        self.assertEqual(dispute.order, self.order)
        self.assertEqual(dispute.raised_by, self.lender)
        self.assertEqual(dispute.status, Dispute.StatusChoices.OPEN)
        self.assertEqual(
            dispute.description, "Missing battery cover and cracked screen."
        )
        self.assertEqual(DisputeEvidence.objects.filter(dispute=dispute).count(), 1)

    def test_return_code_applies_same_single_use_expiry_and_lockout_rules(self) -> None:
        """CP-505: Return codes enforce single-use, 3-hour expiry, and lockout after repeated failures."""
        SystemConfig.objects.create(
            config_key=AUTH_CODE_LOCKOUT_THRESHOLD,
            config_value="2",
        )

        self.client.force_authenticate(user=self.borrower)
        gen_res = self.client.post(self._generate_url())
        code_value = gen_res.json()["code_value"]
        wrong_code = "123456" if code_value != "123456" else "654321"

        self.client.force_authenticate(user=self.lender)
        # 2 wrong attempts trigger lockout
        for _ in range(2):
            res = self.client.post(
                self._verify_url(), {"code": wrong_code}, format="json"
            )
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        locked_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(locked_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Expire lockout window, then verify successfully
        AuthCodeAttempt.objects.filter(attempted_by=self.lender).update(
            attempted_at=timezone.now() - timedelta(minutes=20)
        )
        ok_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(ok_res.status_code, status.HTTP_200_OK)

        # Re-entering used return code after order is Completed is rejected with 400
        reuse_res = self.client.post(
            self._verify_url(), {"code": code_value}, format="json"
        )
        self.assertEqual(reuse_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been used", str(reuse_res.json()))
