from django.urls import reverse
from rest_framework import status

from apps.listings.models import PickupLocation
from apps.listings.tests.base import BaseListingTestCase


class PickupLocationViewTests(BaseListingTestCase):
    """Tests for PickupLocationListView and PickupLocationCreateRetrieveDestroyView."""

    def setUp(self):
        super().setUp()
        self.list_url = reverse("pickup-location-list")
        self.detail_url = reverse(
            "pickup-location-detail", kwargs={"pk": self.pickup_location.pk}
        )
        self.non_existent_url = reverse("pickup-location-detail", kwargs={"pk": 99999})

    # =========================================================================
    # PickupLocationListView Tests
    # =========================================================================

    def test_list_pickup_locations_authenticated_success(self):
        """Authenticated users can list pickup locations."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle paginated or non-paginated results cleanly
        results = response.data.get("results", response.data)
        self.assertGreaterEqual(len(results), 1)
        location_names = [item["name"] for item in results]
        self.assertIn(self.pickup_location.name, location_names)

    def test_list_pickup_locations_ordered_by_name(self):
        """Pickup locations are returned ordered by name alphabetically."""
        PickupLocation.objects.create(name="A Building Lobby")
        PickupLocation.objects.create(name="Z Gate North")

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        names = [item["name"] for item in results]
        self.assertEqual(names, sorted(names))

    def test_list_pickup_locations_unauthenticated(self):
        """Unauthenticated requests cannot list pickup locations."""
        response = self.client.get(self.list_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    # =========================================================================
    # PickupLocationCreateRetrieveDestroyView (Detail) Tests
    # =========================================================================

    def test_retrieve_pickup_location_admin_success(self):
        """Staff/Admin user can retrieve pickup location details."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.pickup_location.id)
        self.assertEqual(response.data["name"], self.pickup_location.name)

    def test_retrieve_pickup_location_regular_user_forbidden(self):
        """Non-admin user cannot access admin pickup location detail endpoint."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_pickup_location_unauthenticated(self):
        """Unauthenticated requests are rejected."""
        response = self.client.get(self.detail_url)
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_retrieve_pickup_location_not_found(self):
        """Admin querying a non-existent location ID receives 404."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.non_existent_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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

    def test_delete_pickup_location_admin_success(self):
        """Admin can delete a pickup location."""
        # Create an unreferenced location so PROTECT constraint on Listing doesn't block deletion
        standalone_location = PickupLocation.objects.create(
            name="Temporary Staging Area",
        )
        standalone_url = reverse(
            "pickup-location-detail", kwargs={"pk": standalone_location.pk}
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(standalone_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            PickupLocation.objects.filter(pk=standalone_location.pk).exists()
        )

    def test_delete_pickup_location_regular_user_forbidden(self):
        """Non-admin cannot delete a pickup location."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            PickupLocation.objects.filter(pk=self.pickup_location.pk).exists()
        )
