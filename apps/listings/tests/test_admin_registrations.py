"""Admin (/admin/) visibility and actions for the sprint-2 listings domain."""

from django.contrib.admin.sites import AdminSite
from django.urls import reverse

from apps.listings.admin import (
    ListingStatusAdmin,
)
from apps.listings.models import (
    AvailabilityWindow,
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)
from apps.listings.tests.base import BaseListingTestCase
from apps.users.models import User


class ListingsAdminRegistrationTests(BaseListingTestCase):
    """Every listings-domain model is registered and reachable under /admin/."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin_user)

    def test_all_listings_models_registered(self):
        from django.contrib import admin

        expected = {
            Listing,
            ListingStatus,
            ListingCategory,
            PickupLocation,
            ListingPhoto,
            AvailabilityWindow,
            BlockedDateRange,
        }
        registered = {m for m, _ in admin.site._registry.items() if m in expected}
        self.assertEqual(registered, expected)

    def test_admin_can_deactivate_a_listing(self) -> None:
        response = self.client.post(
            reverse("admin:listings_listing_changelist"),
            {
                "action": "deactivate_selected",
                "_selected_action": [self.listing.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status.name, "deactivated")

    def test_admin_can_reactivate_a_listing(self) -> None:
        self.listing.status = ListingStatus.objects.create(name="deactivated")
        self.listing.save(update_fields=["status"])

        response = self.client.post(
            reverse("admin:listings_listing_changelist"),
            {
                "action": "reactivate_selected",
                "_selected_action": [self.listing.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status.name, "active")

    def test_deactivate_action_leaves_deleted_listings_alone(self) -> None:
        self.listing.status = ListingStatus.objects.create(name="deleted")
        self.listing.save(update_fields=["status"])

        self.client.post(
            reverse("admin:listings_listing_changelist"),
            {
                "action": "deactivate_selected",
                "_selected_action": [self.listing.pk],
            },
        )
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status.name, "deleted")

    def test_user_model_registered(self):
        from django.contrib import admin

        self.assertIn(User, admin.site._registry)

    def test_admin_index_lists_listings_app(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Listings")
        self.assertContains(response, "Pickup Locations")
        self.assertContains(response, "Blocked Date Ranges")

    def test_admin_changelists_render(self):
        for model in (
            Listing,
            ListingStatus,
            ListingCategory,
            PickupLocation,
            ListingPhoto,
            AvailabilityWindow,
            BlockedDateRange,
            User,
        ):
            url = reverse(
                f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_listing_status_lookup_is_read_only(self):
        """Status names are literal constants in the services; admin cannot rename."""
        site = AdminSite(name="test")
        admin_obj = ListingStatusAdmin(ListingStatus, site)
        request = self.client.get(reverse("admin:index")).wsgi_request
        request.user = self.admin_user
        self.assertFalse(admin_obj.has_add_permission(request))
        self.assertFalse(admin_obj.has_delete_permission(request))

    def test_pickup_soft_delete_action(self):
        loc = PickupLocation.objects.create(name="Action Target Spot")
        url = reverse("admin:listings_pickuplocation_changelist")
        response = self.client.post(
            url,
            {
                "action": "soft_delete_selected",
                "_selected_action": [str(loc.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        loc.refresh_from_db()
        self.assertIsNotNone(loc.deleted_at)
