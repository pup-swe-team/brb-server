from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.models import SystemConfig
from apps.listings.models import (
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.models import Notification
from apps.users.models import User

from .models import Order, OrderStatus
from .services import request_expiry_hours


@override_settings(CRON_SECRET_TOKEN="test-cron-secret")
class LenderResponseTests(APITestCase):
    def setUp(self):
        self.lender = User.objects.create_user(
            email="lender@iskolarngbayan.pup.edu.ph",
            full_name="Lender",
            contact_number="09123456789",
        )
        self.borrower = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            full_name="Borrower",
            contact_number="09987654321",
        )
        self.other_user = User.objects.create_user(
            email="other@iskolarngbayan.pup.edu.ph",
            full_name="Other",
            contact_number="09987654322",
        )
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Calculator",
            description="A calculator",
            category=ListingCategory.objects.create(name="Calculators"),
            condition="Good",
            pickup_location=PickupLocation.objects.create(name="Library"),
            status=ListingStatus.objects.create(name="active"),
        )
        self.start = timezone.localdate() + timedelta(days=3)
        self.end = self.start + timedelta(days=2)
        self.requested, _ = OrderStatus.objects.get_or_create(name="requested")
        self.order = self.make_order("requested")
        self.client.force_authenticate(user=self.lender)

    def make_order(self, status_name, *, start=None, end=None, borrower=None):
        order_status, _ = OrderStatus.objects.get_or_create(name=status_name)
        return Order.objects.create(
            listing=self.listing,
            borrower=borrower or self.borrower,
            start_date=start or self.start,
            end_date=end or self.end,
            status=order_status,
        )

    def post_action(self, action, order=None):
        return self.client.post(
            reverse(f"order-{action}", args=[(order or self.order).pk])
        )

    def run_job(self, secret="Bearer test-cron-secret"):
        headers = {} if secret is None else {"HTTP_AUTHORIZATION": secret}
        return self.client.post(reverse("job-expire-borrow-requests"), **headers)

    def assert_notification(self, event):
        notification = Notification.objects.get()
        self.assertEqual(notification.user, self.borrower)
        self.assertEqual(notification.type.name, event)
        self.assertEqual(notification.reference_id, str(self.order.pk))

    def test_accept_confirms_and_blocks_dates(self):
        response = self.post_action("accept")
        self.assertEqual(response.status_code, 200, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "confirmed")
        self.assertEqual(response.data["status"], "confirmed")
        self.assertEqual(response.data["id"], self.order.pk)
        block = BlockedDateRange.objects.get(order=self.order)
        self.assertEqual((block.start_date, block.end_date), (self.start, self.end))
        self.assert_notification("acceptance")

    def test_decline_releases_only_this_orders_dates(self):
        BlockedDateRange.objects.create(
            listing=self.listing,
            order=self.order,
            start_date=self.start,
            end_date=self.end,
        )
        unrelated = BlockedDateRange.objects.create(
            listing=self.listing,
            start_date=self.end + timedelta(days=5),
            end_date=self.end + timedelta(days=6),
        )
        response = self.post_action("decline")
        self.assertEqual(response.status_code, 200, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "declined")
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())
        self.assertTrue(BlockedDateRange.objects.filter(pk=unrelated.pk).exists())
        self.assert_notification("decline")

    def test_only_authenticated_listing_lender_can_respond(self):
        for actor in (None, self.borrower, self.other_user):
            with self.subTest(actor=actor):
                self.client.force_authenticate(user=actor)
                response = self.post_action("accept")
                self.assertIn(response.status_code, (401, 403))
                self.order.refresh_from_db()
                self.assertEqual(self.order.status.name, "requested")
        self.assertEqual(Notification.objects.count(), 0)

    def test_non_requested_order_cannot_be_answered_twice(self):
        self.assertEqual(self.post_action("decline").status_code, 200)
        self.assertEqual(self.post_action("accept").status_code, 409)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())

    def test_acceptance_conflict_auto_declines_and_notifies(self):
        for blocker in ("confirmed", "active", "manual"):
            with self.subTest(blocker=blocker):
                if blocker == "manual":
                    blocked = BlockedDateRange.objects.create(
                        listing=self.listing,
                        start_date=self.end,
                        end_date=self.end + timedelta(days=1),
                    )
                else:
                    blocked = self.make_order(
                        blocker,
                        start=self.end,
                        end=self.end + timedelta(days=1),
                        borrower=self.other_user,
                    )
                response = self.post_action("accept")
                self.assertEqual(response.status_code, 200, response.data)
                self.order.refresh_from_db()
                self.assertEqual(self.order.status.name, "declined")
                self.assertFalse(
                    BlockedDateRange.objects.filter(order=self.order).exists()
                )
                self.assert_notification("decline")
                blocked.delete()
                Notification.objects.all().delete()
                self.order.status = self.requested
                self.order.save(update_fields=["status"])

    def test_nonoverlapping_booking_does_not_prevent_acceptance(self):
        self.make_order(
            "confirmed",
            start=self.end + timedelta(days=1),
            end=self.end + timedelta(days=2),
            borrower=self.other_user,
        )
        response = self.post_action("accept")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "confirmed")

    def test_deadline_is_inclusive_and_response_expires_order(self):
        now = timezone.now()
        Order.objects.filter(pk=self.order.pk).update(
            created_at=now - timedelta(hours=48)
        )
        with patch("apps.orders.services.timezone.now", return_value=now):
            response = self.post_action("accept")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["status"], "expired")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "expired")
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())
        self.assert_notification("expiry")

    def test_just_before_deadline_can_be_declined(self):
        now = timezone.now()
        Order.objects.filter(pk=self.order.pk).update(
            created_at=now - timedelta(hours=48) + timedelta(microseconds=1)
        )
        with patch("apps.orders.services.timezone.now", return_value=now):
            response = self.post_action("decline")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "declined")

    def test_configured_expiry_and_invalid_fallback(self):
        config = SystemConfig.objects.create(
            config_key="borrow_request_expiry_hours", config_value="2"
        )
        self.assertEqual(request_expiry_hours(), 2)
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(hours=3)
        )
        response = self.post_action("decline")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["status"], "expired")
        for invalid in ("abc", "0", "-1"):
            config.config_value = invalid
            config.save(update_fields=["config_value"])
            self.assertEqual(request_expiry_hours(), 48)

    def test_job_expires_only_overdue_requested_orders_and_is_idempotent(self):
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        recent = self.make_order("requested", borrower=self.other_user)
        confirmed = self.make_order("confirmed", borrower=self.other_user)
        Order.objects.filter(pk=confirmed.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        response = self.run_job()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["expired_order_ids"], [self.order.pk])
        self.order.refresh_from_db()
        recent.refresh_from_db()
        confirmed.refresh_from_db()
        self.assertEqual(self.order.status.name, "expired")
        self.assertEqual(recent.status.name, "requested")
        self.assertEqual(confirmed.status.name, "confirmed")
        self.assert_notification("expiry")
        repeat = self.run_job()
        self.assertEqual(repeat.data["expired_count"], 0)
        self.assertEqual(Notification.objects.count(), 1)

    def test_job_requires_shared_secret_and_post(self):
        for secret, expected in ((None, 401), ("wrong", 401)):
            with self.subTest(secret=secret):
                self.assertEqual(self.run_job(secret).status_code, expected)
        with override_settings(CRON_SECRET_TOKEN=""):
            self.assertEqual(self.run_job().status_code, 503)
        self.assertEqual(
            self.client.get(reverse("job-expire-borrow-requests")).status_code,
            405,
        )
        self.assertEqual(self.order.status.name, "requested")

    def test_job_and_lender_response_cannot_both_transition_order(self):
        self.assertEqual(self.post_action("accept").status_code, 200)
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        self.assertEqual(self.run_job().data["expired_count"], 0)
        self.assertEqual(self.post_action("decline").status_code, 409)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "confirmed")
        self.assertEqual(Notification.objects.count(), 1)

    def test_acceptance_failure_rolls_back_status_and_block(self):
        with patch("apps.orders.services.block_dates_for_order") as block:
            block.side_effect = RuntimeError("calendar storage failed")
            with self.assertRaises(RuntimeError):
                self.post_action("accept")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "requested")
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())
        self.assertEqual(Notification.objects.count(), 0)
