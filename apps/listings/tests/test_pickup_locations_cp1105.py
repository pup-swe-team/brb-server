"""CP-1105 — Manage fixed pickup locations (Admin). Ported from the merged branch."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.listings.models import (
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
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
