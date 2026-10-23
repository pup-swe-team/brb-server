"""CP-403 — Automatically maintained availability calendar. Ported from the merged branch."""

from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.listings.models import (
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.listings.services import (
    block_dates_for_order,
    is_listing_available_for_range,
    release_dates_for_order,
)
from apps.orders.models import Order, OrderStatus

User = get_user_model()


class AvailabilityCalendarLogicTests(APITestCase):
    """
    Test suite for CP-403: Automatically maintained availability calendar.
    Covers blocking dates on order confirmation, releasing dates on cancel/complete,
    idempotency, availability query helpers, model constraints, and serializer representation.
    """

    def setUp(self) -> None:
        self.lender = User.objects.create_user(
            email="lender@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Juan",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.lender.account_status = User.AccountStatusChoices.ACTIVE
        self.lender.save(update_fields=["account_status"])

        self.borrower = User.objects.create_user(
            email="borrower2@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Maria",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.borrower.account_status = User.AccountStatusChoices.ACTIVE
        self.borrower.save(update_fields=["account_status"])

        self.category, _ = ListingCategory.objects.get_or_create(name="Calculators")
        self.listing_status, _ = ListingStatus.objects.get_or_create(name="active")
        self.location = PickupLocation.objects.create(
            name="Main Gate", description="Near guardhouse"
        )

        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Scientific Calculator fx-991EX",
            description="Perfect for engineering calculus",
            category=self.category,
            pickup_location=self.location,
            status=self.listing_status,
            condition="Like New",
            rate_per_day=20.00,
        )

        self.confirmed_status, _ = OrderStatus.objects.get_or_create(name="confirmed")
        self.cancelled_status, _ = OrderStatus.objects.get_or_create(name="cancelled")

        self.order1 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            status=self.confirmed_status,
        )

    def test_block_dates_for_confirmed_order(self) -> None:
        """Blocking dates for a confirmed order creates a BlockedDateRange."""
        blocked = block_dates_for_order(self.order1)
        self.assertEqual(blocked.listing, self.listing)
        self.assertEqual(blocked.order, self.order1)
        self.assertEqual(blocked.start_date, date(2026, 11, 1))
        self.assertEqual(blocked.end_date, date(2026, 11, 5))
        self.assertTrue(
            BlockedDateRange.objects.filter(
                listing=self.listing, order=self.order1
            ).exists()
        )

    def test_block_dates_invalid_range_raises_error(self) -> None:
        """Attempting to block an order where start_date > end_date raises ValueError."""
        invalid_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 5),
            status=self.confirmed_status,
        )
        with self.assertRaises(ValueError):
            block_dates_for_order(invalid_order)

    def test_block_dates_is_idempotent_and_syncs_updates(self) -> None:
        """Repeated calls to block_dates_for_order update existing range rather than duplicating."""
        first = block_dates_for_order(self.order1)
        self.assertEqual(BlockedDateRange.objects.filter(order=self.order1).count(), 1)

        # Update order dates and block again
        self.order1.end_date = date(2026, 11, 7)
        self.order1.save(update_fields=["end_date"])

        second = block_dates_for_order(self.order1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(BlockedDateRange.objects.filter(order=self.order1).count(), 1)
        self.assertEqual(second.end_date, date(2026, 11, 7))

    def test_release_dates_for_order(self) -> None:
        """Releasing dates deletes the BlockedDateRange associated with the order."""
        block_dates_for_order(self.order1)
        self.assertTrue(BlockedDateRange.objects.filter(order=self.order1).exists())

        deleted_count = release_dates_for_order(self.order1)
        self.assertEqual(deleted_count, 1)
        self.assertFalse(BlockedDateRange.objects.filter(order=self.order1).exists())

    def test_release_dates_is_idempotent(self) -> None:
        """Calling release_dates_for_order when no range exists returns 0 safely."""
        deleted_count = release_dates_for_order(self.order1)
        self.assertEqual(deleted_count, 0)

    def test_multiple_orders_create_independent_blocked_ranges(self) -> None:
        """Distinct orders on the same listing maintain separate blocked date ranges."""
        order2 = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 15),
            status=self.confirmed_status,
        )

        block_dates_for_order(self.order1)
        block_dates_for_order(order2)

        self.assertEqual(
            BlockedDateRange.objects.filter(listing=self.listing).count(), 2
        )

        # Release order 1; order 2 remains
        release_dates_for_order(self.order1)
        self.assertEqual(
            BlockedDateRange.objects.filter(listing=self.listing).count(), 1
        )
        self.assertTrue(BlockedDateRange.objects.filter(order=order2).exists())

    def test_is_listing_available_for_range(self) -> None:
        """Availability check handles non-overlapping and overlapping dates accurately."""
        block_dates_for_order(self.order1)  # Blocked: Nov 1 to Nov 5

        # Completely before -> available
        self.assertTrue(
            is_listing_available_for_range(
                self.listing, date(2026, 10, 20), date(2026, 10, 31)
            )
        )
        # Completely after -> available
        self.assertTrue(
            is_listing_available_for_range(
                self.listing, date(2026, 11, 6), date(2026, 11, 9)
            )
        )
        # Overlap front (Oct 30 - Nov 2) -> unavailable
        self.assertFalse(
            is_listing_available_for_range(
                self.listing, date(2026, 10, 30), date(2026, 11, 2)
            )
        )
        # Overlap back (Nov 4 - Nov 8) -> unavailable
        self.assertFalse(
            is_listing_available_for_range(
                self.listing, date(2026, 11, 4), date(2026, 11, 8)
            )
        )
        # Exact match (Nov 1 - Nov 5) -> unavailable
        self.assertFalse(
            is_listing_available_for_range(
                self.listing, date(2026, 11, 1), date(2026, 11, 5)
            )
        )
        # Encompassing (Oct 25 - Nov 10) -> unavailable
        self.assertFalse(
            is_listing_available_for_range(
                self.listing, date(2026, 10, 25), date(2026, 11, 10)
            )
        )
        # With exclude_order_id set to order1 -> available
        self.assertTrue(
            is_listing_available_for_range(
                self.listing,
                date(2026, 11, 1),
                date(2026, 11, 5),
                exclude_order_id=self.order1.pk,
            )
        )

    def test_listing_detail_endpoint_exposes_blocked_dates(self) -> None:
        """Listing detail endpoint includes blocked_dates in its serialized response."""
        block_dates_for_order(self.order1)
        self.client.force_authenticate(user=self.borrower)

        url = reverse("listing-detail", kwargs={"pk": self.listing.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("blocked_dates", response.data)
        self.assertEqual(len(response.data["blocked_dates"]), 1)
        self.assertEqual(response.data["blocked_dates"][0]["start_date"], "2026-11-01")
        self.assertEqual(response.data["blocked_dates"][0]["end_date"], "2026-11-05")
