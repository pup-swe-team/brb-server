from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import SystemConfig
from apps.listings.models import (
    AvailabilityWindow,
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.models import Notification
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)

from .models import Order, OrderStatus


class BorrowRequestTests(APITestCase):
    def setUp(self):
        self.url = reverse("order-request")
        self.today = timezone.localdate()
        self.start = self.today + timedelta(days=2)
        self.end = self.today + timedelta(days=5)
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
        approved, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        IdentityDocument.objects.create(
            user=self.borrower,
            document_type=doc_type,
            id_number="BORROWER-1",
            document_data=b"test",
            status=approved,
            consent_given=True,
            consented_at=timezone.now(),
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
        self.window = AvailabilityWindow.objects.create(
            listing=self.listing,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
        )
        self.client.force_authenticate(user=self.borrower)

    def payload(self, **overrides):
        return {
            "listing_id": self.listing.pk,
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            **overrides,
        }

    def assert_rejected(self, payload, expected_status=status.HTTP_400_BAD_REQUEST):
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, expected_status, response.data)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def make_order(self, name, start=None, end=None):
        order_status, _ = OrderStatus.objects.get_or_create(name=name)
        return Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=start or self.start,
            end_date=end or self.end,
            status=order_status,
        )

    def test_success_creates_requested_order_and_notifies_lender(self):
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        order = Order.objects.get()
        self.assertEqual(order.status.name, "requested")
        self.assertEqual(order.borrower, self.borrower)
        self.assertEqual(order.listing, self.listing)
        self.assertEqual(
            response.data,
            {
                "id": order.pk,
                "listing_id": self.listing.pk,
                "borrower_id": self.borrower.pk,
                "start_date": self.start.isoformat(),
                "end_date": self.end.isoformat(),
                "status": "requested",
            },
        )
        notification = Notification.objects.get()
        self.assertEqual(notification.user, self.lender)
        self.assertEqual(notification.type.name, "new_request")
        self.assertEqual(notification.reference_id, str(order.pk))

    def test_requires_authentication_and_verified_identity(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertIn(response.status_code, (401, 403))
        unverified = User.objects.create_user(
            email="unverified@iskolarngbayan.pup.edu.ph",
            full_name="Unverified",
            contact_number="09111111111",
        )
        self.client.force_authenticate(user=unverified)
        self.assert_rejected(self.payload(), status.HTTP_403_FORBIDDEN)

    def test_invalid_or_missing_dates_are_rejected(self):
        for payload in (
            self.payload(start_date=(self.today - timedelta(days=1)).isoformat()),
            self.payload(end_date=(self.start - timedelta(days=1)).isoformat()),
            self.payload(start_date="invalid"),
            {"listing_id": self.listing.pk, "start_date": self.start.isoformat()},
        ):
            with self.subTest(payload=payload):
                self.assert_rejected(payload)

    def test_own_listing_and_inactive_listing_are_rejected(self):
        self.listing.lender = self.borrower
        self.listing.save(update_fields=["lender"])
        self.assert_rejected(self.payload())
        self.listing.lender = self.lender
        self.listing.status = ListingStatus.objects.create(name="deactivated")
        self.listing.save(update_fields=["lender", "status"])
        self.assert_rejected(self.payload())

    def test_range_must_fit_inside_one_window_inclusively(self):
        self.assert_rejected(
            self.payload(
                end_date=(self.window.end_date + timedelta(days=1)).isoformat()
            )
        )
        self.window.end_date = self.start
        self.window.save(update_fields=["end_date"])
        AvailabilityWindow.objects.create(
            listing=self.listing,
            start_date=self.start + timedelta(days=1),
            end_date=self.end,
        )
        self.assert_rejected(self.payload())
        response = self.client.post(
            self.url,
            self.payload(end_date=self.start.isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_confirmed_and_active_orders_block_inclusive_overlaps(self):
        for name in ("confirmed", "active"):
            with self.subTest(status=name):
                order = self.make_order(name)
                response = self.client.post(
                    self.url,
                    self.payload(start_date=self.end.isoformat()),
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(Order.objects.count(), 1)
                self.assertEqual(Notification.objects.count(), 0)
                order.delete()

    def test_nonoverlapping_and_requested_orders_do_not_block_dates(self):
        self.make_order("confirmed", self.today, self.today + timedelta(days=1))
        self.make_order("requested", self.start, self.end)
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_blocked_range_rejects_request(self):
        BlockedDateRange.objects.create(
            listing=self.listing,
            start_date=self.end,
            end_date=self.end + timedelta(days=1),
        )
        self.assert_rejected(self.payload())

    def test_limit_counts_requested_confirmed_and_active(self):
        for name in ("requested", "confirmed", "active"):
            self.make_order(name, self.today, self.today + timedelta(days=1))
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("borrowing limit", str(response.data))
        self.assertEqual(Order.objects.count(), 3)
        self.assertEqual(Notification.objects.count(), 0)

    def test_configured_limit_and_invalid_fallback(self):
        config = SystemConfig.objects.create(
            config_key="borrowing_limit", config_value="1"
        )
        self.make_order("requested", self.today, self.today + timedelta(days=1))
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        for invalid in ("abc", "0", "-1"):
            with self.subTest(config_value=invalid):
                config.config_value = invalid
                config.save(update_fields=["config_value"])
                response = self.client.post(self.url, self.payload(), format="json")
                self.assertEqual(response.status_code, 201, response.data)
                Order.objects.filter(pk=response.data["id"]).delete()

    def test_notification_failure_rolls_back_order(self):
        with patch("apps.orders.services.Notification.objects.create") as create:
            create.side_effect = RuntimeError("notification storage failed")
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
