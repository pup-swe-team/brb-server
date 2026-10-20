"""Pickup location endpoints unified under CP-1105 (soft-delete, user-readable)."""

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.listings.models import PickupLocation
from apps.listings.tests.base import BaseListingTestCase


class PickupLocationViewTests(BaseListingTestCase):
    """CP-1105 pickup-locations routes: read for any user, writes for staff, soft delete."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse("pickup-location-list-create")
        self.detail_url = reverse(
            "pickup-location-detail", kwargs={"pk": self.pickup_location.pk}
        )
        self.non_existent_url = reverse("pickup-location-detail", kwargs={"pk": 99999})

    def test_list_pickup_locations_authenticated_success(self):
        """Authenticated users can list pickup locations (unpaginated dropdown set)."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        location_names = [item["name"] for item in response.data]
        self.assertIn(self.pickup_location.name, location_names)

    def test_list_pickup_locations_ordered_by_name(self):
        """Pickup locations are returned ordered by name alphabetically."""
        PickupLocation.objects.create(name="A Building Lobby")
        PickupLocation.objects.create(name="Z Gate North")

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.list_url)

        names = [item["name"] for item in response.data]
        self.assertEqual(names, sorted(names))

    def test_list_excludes_soft_deleted_locations(self):
        """Soft-deleted locations never appear in the dropdown list."""
        PickupLocation.objects.create(name="Retired Spot", deleted_at=timezone.now())

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.list_url)

        names = [item["name"] for item in response.data]
        self.assertNotIn("Retired Spot", names)
        self.assertIn(self.pickup_location.name, names)

    def test_list_pickup_locations_unauthenticated(self):
        """Unauthenticated requests cannot list pickup locations."""
        response = self.client.get(self.list_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_retrieve_pickup_location_authenticated_success(self):
        """Any authenticated user can read pickup location details (CP-1105)."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.pickup_location.id)
        self.assertEqual(response.data["name"], self.pickup_location.name)

    def test_retrieve_pickup_location_unauthenticated(self):
        """Unauthenticated requests are rejected."""
        response = self.client.get(self.detail_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_retrieve_pickup_location_not_found(self):
        """A non-existent location ID receives 404."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.non_existent_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_soft_deleted_location_not_found(self):
        """A soft-deleted location behaves as gone (404)."""
        self.pickup_location.deleted_at = timezone.now()
        self.pickup_location.save(update_fields=["deleted_at"])

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_pickup_location_admin_success(self):
        """Staff admin can create a designated pickup location."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.list_url,
            {"name": "New Admin Spot", "description": "Beside the covered walkway"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Admin Spot")
        self.assertTrue(PickupLocation.objects.filter(name="New Admin Spot").exists())

    def test_create_pickup_location_regular_user_forbidden(self):
        """Non-admin cannot create a pickup location."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.list_url, {"name": "Unauthorized Spot"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            PickupLocation.objects.filter(name="Unauthorized Spot").exists()
        )

    def test_update_pickup_location_admin_success(self):
        """Admin can update pickup location name."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(
            self.detail_url, data={"name": "Renamed Campus Library"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.pickup_location.refresh_from_db()
        self.assertEqual(self.pickup_location.name, "Renamed Campus Library")

    def test_update_pickup_location_regular_user_forbidden(self):
        """Non-admin cannot update pickup location."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            self.detail_url, data={"name": "Unauthorized Name"}
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.pickup_location.refresh_from_db()
        self.assertNotEqual(self.pickup_location.name, "Unauthorized Name")

    def test_delete_pickup_location_admin_soft_delete(self):
        """Admin delete sets deleted_at; the row survives for audit/history."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.pickup_location.refresh_from_db()
        self.assertIsNotNone(self.pickup_location.deleted_at)

        list_response = self.client.get(self.list_url)
        names = [item["name"] for item in list_response.data]
        self.assertNotIn(self.pickup_location.name, names)

    def test_delete_referenced_pickup_location_soft_delete(self):
        """Deleting a location still used by a listing is a clean 204 (soft delete)."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.pickup_location_id, self.pickup_location.pk)

    def test_delete_pickup_location_regular_user_forbidden(self):
        """Non-admin cannot delete a pickup location."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.pickup_location.refresh_from_db()
        self.assertIsNone(self.pickup_location.deleted_at)
