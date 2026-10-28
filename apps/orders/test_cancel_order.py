from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.listings.models import (
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.listings.services import block_dates_for_order
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus
from apps.users.models import User


class CancelOrderTests(APITestCase):
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
        self.stranger = User.objects.create_user(
            email="stranger@iskolarngbayan.pup.edu.ph",
            full_name="Stranger",
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
        self.start = timezone.localdate() + timedelta(days=2)
        self.end = self.start + timedelta(days=2)
        self.order = self.make_order("requested")

    def make_order(self, status_name):
        status, _ = OrderStatus.objects.get_or_create(name=status_name)
        return Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=self.start,
            end_date=self.end,
            status=status,
        )

    def cancel(self, order=None, reason="Plans changed"):
        return self.client.post(
            reverse("order-cancel", args=[(order or self.order).pk]),
            {"reason": reason},
            format="json",
        )

    def test_borrower_and_lender_can_cancel_requested_or_confirmed(self):
        for actor in (self.borrower, self.lender):
            for status_name in ("requested", "confirmed"):
                with self.subTest(actor=actor.pk, status=status_name):
                    order = self.make_order(status_name)
                    if status_name == "confirmed":
                        block_dates_for_order(order)
                    else:
                        BlockedDateRange.objects.create(
                            listing=self.listing,
                            order=order,
                            start_date=self.start,
                            end_date=self.end,
                        )
                    self.client.force_authenticate(user=actor)
                    response = self.cancel(order, "  Plans changed  ")
                    self.assertEqual(response.status_code, 200, response.data)
                    order.refresh_from_db()
                    self.assertEqual(order.status.name, "cancelled")
                    self.assertEqual(order.cancel_reason, "Plans changed")
                    self.assertEqual(response.data["cancel_reason"], "Plans changed")
                    self.assertEqual(response.data["status"], "cancelled")
                    self.assertEqual(response.data["listing_id"], self.listing.pk)
                    self.assertEqual(response.data["borrower_id"], self.borrower.pk)
                    self.assertEqual(response.data["lender_id"], self.lender.pk)
                    self.assertIn("created_at", response.data)
                    self.assertIn("updated_at", response.data)
                    self.assertFalse(
                        BlockedDateRange.objects.filter(order=order).exists()
                    )
                    notification = Notification.objects.get(reference_id=str(order.pk))
                    self.assertEqual(notification.type.name, "cancellation")
                    self.assertEqual(
                        notification.user,
                        self.lender if actor == self.borrower else self.borrower,
                    )

    def test_cancel_releases_only_its_own_block(self):
        self.client.force_authenticate(user=self.borrower)
        block_dates_for_order(self.order)
        unrelated = BlockedDateRange.objects.create(
            listing=self.listing,
            start_date=self.end + timedelta(days=2),
            end_date=self.end + timedelta(days=3),
        )
        self.assertEqual(self.cancel().status_code, 200)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())
        self.assertTrue(BlockedDateRange.objects.filter(pk=unrelated.pk).exists())

    def test_reason_is_required_and_whitespace_rejected(self):
        self.client.force_authenticate(user=self.borrower)
        for payload in ({}, {"reason": ""}, {"reason": " \n\t "}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    reverse("order-cancel", args=[self.order.pk]),
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "requested")
        self.assertEqual(self.order.cancel_reason, "")
        self.assertEqual(Notification.objects.count(), 0)

    def test_authentication_and_party_permissions(self):
        for actor in (None, self.stranger):
            with self.subTest(actor=actor):
                self.client.force_authenticate(user=actor)
                response = self.cancel()
                self.assertIn(response.status_code, (401, 403))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "requested")
        self.assertEqual(Notification.objects.count(), 0)

    def test_only_requested_or_confirmed_can_be_cancelled(self):
        self.client.force_authenticate(user=self.borrower)
        for status_name in (
            "active",
            "declined",
            "expired",
            "cancelled",
            "returned",
            "completed",
        ):
            with self.subTest(status=status_name):
                order = self.make_order(status_name)
                response = self.cancel(order)
                self.assertEqual(response.status_code, 409, response.data)
                order.refresh_from_db()
                self.assertEqual(order.status.name, status_name)
                self.assertEqual(order.cancel_reason, "")
        self.assertEqual(Notification.objects.count(), 0)

    def test_detail_is_party_only_and_shows_reason(self):
        self.client.force_authenticate(user=self.borrower)
        self.assertEqual(self.cancel(reason="No longer needed").status_code, 200)
        url = reverse("order-detail", args=[self.order.pk])
        for actor in (self.borrower, self.lender):
            with self.subTest(actor=actor.pk):
                self.client.force_authenticate(user=actor)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["cancel_reason"], "No longer needed")
                self.assertEqual(response.data["status"], "cancelled")
        for actor in (None, self.stranger):
            with self.subTest(actor=actor):
                self.client.force_authenticate(user=actor)
                self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_missing_order_returns_404(self):
        self.client.force_authenticate(user=self.borrower)
        missing = self.order.pk + 999
        self.assertEqual(
            self.client.post(
                reverse("order-cancel", args=[missing]),
                {"reason": "Cannot attend"},
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("order-detail", args=[missing])).status_code, 404
        )

    def test_notification_failure_rolls_back_cancellation_and_date_release(self):
        self.client.force_authenticate(user=self.borrower)
        block_dates_for_order(self.order)
        with patch("apps.orders.services.Notification.objects.create") as create:
            create.side_effect = RuntimeError("notification storage failed")
            with self.assertRaises(RuntimeError):
                self.cancel()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "requested")
        self.assertEqual(self.order.cancel_reason, "")
        self.assertTrue(BlockedDateRange.objects.filter(order=self.order).exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_transition_ordering_cannot_overwrite_decline_or_expiry(self):
        self.client.force_authenticate(user=self.lender)
        self.assertEqual(
            self.client.post(
                reverse("order-decline", args=[self.order.pk])
            ).status_code,
            200,
        )
        self.assertEqual(self.cancel().status_code, 409)
        expired = self.make_order("expired")
        self.assertEqual(self.cancel(expired).status_code, 409)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "declined")
        self.assertEqual(self.order.cancel_reason, "")

    def test_confirmed_order_remains_cancellable_after_acceptance(self):
        self.client.force_authenticate(user=self.lender)
        self.assertEqual(
            self.client.post(reverse("order-accept", args=[self.order.pk])).status_code,
            200,
        )
        self.assertTrue(BlockedDateRange.objects.filter(order=self.order).exists())
        self.client.force_authenticate(user=self.borrower)
        response = self.cancel(reason="Schedule conflict")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "cancelled")

    def test_cancellation_wins_before_lender_response(self):
        self.client.force_authenticate(user=self.borrower)
        self.assertEqual(self.cancel().status_code, 200)
        self.client.force_authenticate(user=self.lender)
        self.assertEqual(
            self.client.post(reverse("order-accept", args=[self.order.pk])).status_code,
            409,
        )
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order).exists())

    def test_overdue_requested_order_can_cancel_before_expiry_sweep(self):
        Order.objects.filter(pk=self.order.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        self.client.force_authenticate(user=self.borrower)
        response = self.cancel(reason="No longer needed")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelled")
