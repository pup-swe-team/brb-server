from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderStatus

from .models import (
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from .services import (
    block_dates_for_order,
    is_listing_available_for_range,
    release_dates_for_order,
)

User = get_user_model()


class PickupLocationManagementTests(APITestCase):
    """
    Test suite for CP-1105: Manage fixed pickup locations (Admin).
    Covers pickup location CRUD endpoints, soft-delete behavior,
    admin authority enforcement, and listing dropdown availability.
    """

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Student",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.user.account_status = User.AccountStatusChoices.ACTIVE
        self.user.save(update_fields=["account_status"])

        self.admin = User.objects.create_user(
            email="admin@pup.edu.ph",
            password="StrongPassword123!",
            full_name="Platform Admin",
            affiliation=User.AffiliationChoices.FACULTY,
            is_staff=True,
        )
        self.admin.account_status = User.AccountStatusChoices.ACTIVE
        self.admin.save(update_fields=["account_status", "is_staff"])

        self.loc1 = PickupLocation.objects.create(
            name="Main Library Entrance",
            description="Front steps near the turnstiles",
        )
        self.loc2 = PickupLocation.objects.create(
            name="Charlie Del Rosario Building",
            description="Student activity center lobby",
        )
        self.deleted_loc = PickupLocation.objects.create(
            name="Old Gymnasium Gate",
            description="Under renovation",
            deleted_at=timezone.now(),
        )

        self.list_url = reverse("pickup-location-list-create")
        self.detail_url = reverse("pickup-location-detail", kwargs={"pk": self.loc1.pk})

    # --- Authentication and Authorization (D-03, FR14) ---

    def test_unauthenticated_user_cannot_list_locations(self) -> None:
        """Unauthenticated caller is denied with 401."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_can_list_active_locations(self) -> None:
        """Any authenticated user can fetch active locations for dropdowns."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        names = [item["name"] for item in response.data]
        self.assertIn("Main Library Entrance", names)
        self.assertIn("Charlie Del Rosario Building", names)
        self.assertNotIn("Old Gymnasium Gate", names)

    def test_regular_user_cannot_create_location(self) -> None:
        """Non-admin user cannot create a pickup location (403)."""
        self.client.force_authenticate(user=self.user)
        payload = {"name": "Unauthorized Spot", "description": "Lobby"}
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_location(self) -> None:
        """Admin can create a new approved campus pickup location."""
        self.client.force_authenticate(user=self.admin)
        payload = {
            "name": "Ninoy Aquino Learning Resources Center",
            "description": "Ground floor information desk",
        }
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], payload["name"])
        self.assertEqual(response.data["description"], payload["description"])
        self.assertTrue(PickupLocation.objects.filter(name=payload["name"]).exists())

    def test_cannot_create_location_with_blank_name(self) -> None:
        """Name is required and cannot be blank or whitespace."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            self.list_url, {"name": "   ", "description": "Test"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_regular_user_can_retrieve_location_detail(self) -> None:
        """Authenticated user can view location detail."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.loc1.pk)
        self.assertEqual(response.data["name"], self.loc1.name)

    def test_cannot_retrieve_soft_deleted_location_detail(self) -> None:
        """Deleted location returns 404 on detail retrieve."""
        self.client.force_authenticate(user=self.user)
        deleted_url = reverse(
            "pickup-location-detail", kwargs={"pk": self.deleted_loc.pk}
        )
        response = self.client.get(deleted_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regular_user_cannot_update_location(self) -> None:
        """Non-admin user cannot update a pickup location."""
        self.client.force_authenticate(user=self.user)
        response = self.client.put(
            self.detail_url,
            {"name": "Renamed Spot", "description": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_update_location_put_and_patch(self) -> None:
        """Admin can update location via PUT and PATCH."""
        self.client.force_authenticate(user=self.admin)

        # Full update (PUT)
        put_response = self.client.put(
            self.detail_url,
            {
                "name": "Main Library Gate 1",
                "description": "Right side entrance",
            },
            format="json",
        )
        self.assertEqual(put_response.status_code, status.HTTP_200_OK)
        self.loc1.refresh_from_db()
        self.assertEqual(self.loc1.name, "Main Library Gate 1")
        self.assertEqual(self.loc1.description, "Right side entrance")

        # Partial update (PATCH)
        patch_response = self.client.patch(
            self.detail_url,
            {"description": "Updated desk info"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.loc1.refresh_from_db()
        self.assertEqual(self.loc1.name, "Main Library Gate 1")
        self.assertEqual(self.loc1.description, "Updated desk info")

    def test_regular_user_cannot_delete_location(self) -> None:
        """Non-admin user cannot delete a location."""
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_soft_delete_location(self) -> None:
        """Admin delete performs soft-delete (sets deleted_at, returns 204)."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.loc1.refresh_from_db()
        self.assertIsNotNone(self.loc1.deleted_at)

        # Ensure no longer returned in list
        list_response = self.client.get(self.list_url)
        names = [item["name"] for item in list_response.data]
        self.assertNotIn(self.loc1.name, names)

        # Ensure detail endpoint returns 404
        detail_response = self.client.get(self.detail_url)
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_soft_delete_preserves_existing_listing_fk(self) -> None:
        """Soft-deleting a location does not violate PROTECT foreign key on listings."""
        category, _ = ListingCategory.objects.get_or_create(name="Textbooks")
        listing_status, _ = ListingStatus.objects.get_or_create(name="active")

        listing = Listing.objects.create(
            lender=self.user,
            title="University Physics Vol 1",
            description="Good condition physics textbook",
            category=category,
            pickup_location=self.loc1,
            status=listing_status,
            condition="Good",
            rate_per_day=15.00,
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Listing still exists and still points to loc1
        listing.refresh_from_db()
        self.assertEqual(listing.pickup_location_id, self.loc1.pk)
        self.assertIsNotNone(listing.pickup_location.deleted_at)


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
