from decimal import Decimal

from django.urls import reverse
from rest_framework import status

from apps.listings.models import Listing
from apps.listings.tests.base import BaseListingTestCase


class ListingDetailViewTests(BaseListingTestCase):
    """Tests for the ListingDetailView endpoint."""

    def setUp(self):
        super().setUp()
        self.detail_url = reverse("listing-detail", kwargs={"pk": self.listing.pk})
        self.non_existent_url = reverse("listing-detail", kwargs={"pk": 99999})

    # =========================================================================
    # GET (Retrieve) Tests
    # =========================================================================

    def test_retrieve_listing_by_owner_success(self):
        """Owner can retrieve the listing and inspect all serialized fields."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["id"], self.listing.id)
        self.assertEqual(data["title"], self.listing.title)
        self.assertEqual(data["description"], self.listing.description)
        self.assertEqual(data["condition"], self.listing.condition)
        self.assertEqual(Decimal(data["rate_per_day"]), Decimal("25.00"))
        self.assertTrue(data["is_ownership_confirmed"])

        # Validate nested representations
        self.assertEqual(
            data["lender"],
            {"id": self.owner.id, "full_name": self.owner.full_name},
        )
        self.assertEqual(
            data["category"],
            {"id": self.category.id, "name": self.category.name},
        )
        self.assertEqual(
            data["pickup_location"],
            {"id": self.pickup_location.id, "name": self.pickup_location.name},
        )
        self.assertEqual(
            data["status"],
            {"id": self.status_active.id, "name": self.status_active.name},
        )
        self.assertEqual(len(data["availability_windows"]), 1)
        self.assertEqual(data["availability_windows"][0]["start_date"], "2026-10-10")
        self.assertEqual(data["availability_windows"][0]["end_date"], "2026-10-20")

    def test_retrieve_listing_by_other_authenticated_user_success(self):
        """Non-owner authenticated users can view the listing details."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.listing.id)

    def test_retrieve_listing_unauthenticated(self):
        """Unauthenticated requests are rejected."""
        response = self.client.get(self.detail_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_retrieve_listing_not_found(self):
        """Requesting a non-existent listing ID returns 404."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.non_existent_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # PATCH / PUT (Update) Tests
    # =========================================================================

    def test_partial_update_by_owner_success(self):
        """Owner can partially update listing fields via PATCH."""
        self.client.force_authenticate(user=self.owner)
        payload = {
            "title": "Calculus 11th Edition Updated",
            "rate_per_day": "30.00",
        }
        response = self.client.patch(self.detail_url, data=payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.title, "Calculus 11th Edition Updated")
        self.assertEqual(self.listing.rate_per_day, Decimal("30.00"))

    def test_full_update_by_owner_success(self):
        """Owner can perform full update via PUT."""
        self.client.force_authenticate(user=self.owner)
        payload = {
            "title": "Calculus: Complete Edition",
            "description": "Updated description with problem sets.",
            "condition": "Like New",
            "rate_per_day": "35.00",
            "is_ownership_confirmed": True,
        }
        response = self.client.put(self.detail_url, data=payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.title, "Calculus: Complete Edition")
        self.assertEqual(self.listing.condition, "Like New")
        self.assertEqual(self.listing.rate_per_day, Decimal("35.00"))

    def test_update_by_non_owner_forbidden(self):
        """A user other than the owner cannot update the listing."""
        self.client.force_authenticate(user=self.other_user)
        payload = {"title": "Attempted Unauthorized Title"}
        response = self.client.patch(self.detail_url, data=payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.listing.refresh_from_db()
        self.assertNotEqual(self.listing.title, "Attempted Unauthorized Title")

    def test_update_unauthenticated(self):
        """Unauthenticated user cannot update the listing."""
        payload = {"title": "Attempted Unauthorized Title"}
        response = self.client.patch(self.detail_url, data=payload)

        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_update_not_found(self):
        """Updating a non-existent listing ID returns 404."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.patch(self.non_existent_url, data={"title": "New"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # =========================================================================
    # DELETE Tests
    # =========================================================================

    def test_delete_by_owner_success(self):
        """Owner can delete their own listing."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_delete_by_non_owner_forbidden(self):
        """Non-owner cannot delete another user's listing."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_delete_unauthenticated(self):
        """Unauthenticated request cannot delete listing."""
        response = self.client.delete(self.detail_url)

        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_delete_not_found(self):
        """Deleting non-existent listing returns 404."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(self.non_existent_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
