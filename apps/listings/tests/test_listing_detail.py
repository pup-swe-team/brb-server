from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.listings.models import Listing
from apps.listings.tests.base import BaseListingTestCase
from apps.orders.models import Order, OrderStatus
from apps.reviews.models import Review
from apps.users.models import User


class ListingDetailViewTests(BaseListingTestCase):
    """Tests for the ListingDetailView endpoint (CP-303)."""

    def setUp(self):
        super().setUp()
        self.detail_url = reverse("listing-detail", kwargs={"pk": self.listing.pk})
        self.non_existent_url = reverse("listing-detail", kwargs={"pk": 99999})
        self.order_status_completed, _ = OrderStatus.objects.get_or_create(
            name="completed"
        )

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

        # Validate nested lender representation (profile summary)
        self.assertEqual(
            data["lender"],
            {
                "id": self.owner.id,
                "full_name": self.owner.full_name,
                "photo": None,
                "affiliation": self.owner.affiliation,
                "bio": self.owner.bio,
                "rating_average": None,
                "total_reviews": 0,
            },
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
        self.assertEqual(data["reviews"], [])

    def test_retrieve_listing_by_other_authenticated_user_success(self):
        """Non-owner authenticated users can view the listing details."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.listing.id)

    def test_retrieve_listing_with_reviews_and_ratings(self):
        """Detail page aggregates item reviews and lender rating statistics."""
        # Create an order with borrower reviewing the item
        order1 = Order.objects.create(
            listing=self.listing,
            borrower=self.other_user,
            start_date=date(2026, 10, 11),
            end_date=date(2026, 10, 15),
            status=self.order_status_completed,
        )
        review1 = Review.objects.create(
            order=order1,
            reviewer=self.other_user,
            rating=5,
            comment="Excellent textbook in pristine condition!",
        )

        # Create a second borrower and second order with review
        second_borrower = User.objects.create_user(
            email="second_borrower@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Second Borrower",
            contact_number="09120000000",
        )
        order2 = Order.objects.create(
            listing=self.listing,
            borrower=second_borrower,
            start_date=date(2026, 10, 16),
            end_date=date(2026, 10, 18),
            status=self.order_status_completed,
        )
        review2 = Review.objects.create(
            order=order2,
            reviewer=second_borrower,
            rating=4,
            comment="Very helpful and accommodating lender.",
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        # Lender reputation summary (average of 5 and 4 = 4.5)
        self.assertEqual(data["lender"]["rating_average"], 4.5)
        self.assertEqual(data["lender"]["total_reviews"], 2)

        # Reviews list: newest first
        reviews = data["reviews"]
        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0]["id"], review2.id)
        self.assertEqual(reviews[0]["rating"], 4)
        self.assertEqual(
            reviews[0]["comment"], "Very helpful and accommodating lender."
        )
        self.assertEqual(
            reviews[0]["reviewer"],
            {
                "id": second_borrower.id,
                "full_name": second_borrower.full_name,
                "photo": None,
            },
        )

        self.assertEqual(reviews[1]["id"], review1.id)
        self.assertEqual(reviews[1]["rating"], 5)
        self.assertEqual(
            reviews[1]["comment"], "Excellent textbook in pristine condition!"
        )
        self.assertEqual(
            reviews[1]["reviewer"],
            {
                "id": self.other_user.id,
                "full_name": self.other_user.full_name,
                "photo": None,
            },
        )

    def test_retrieve_listing_excludes_deleted_reviews(self):
        """Soft-deleted reviews are excluded from listing reviews and lender rating calculation."""
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.other_user,
            start_date=date(2026, 10, 11),
            end_date=date(2026, 10, 15),
            status=self.order_status_completed,
        )
        Review.objects.create(
            order=order,
            reviewer=self.other_user,
            rating=1,
            comment="Spam review that was moderated.",
            deleted_at=timezone.now(),
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["reviews"], [])
        self.assertIsNone(response.data["lender"]["rating_average"])
        self.assertEqual(response.data["lender"]["total_reviews"], 0)

    def test_retrieve_listing_excludes_lender_counter_reviews(self):
        """Lender's review of the borrower is not included in item reviews."""
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.other_user,
            start_date=date(2026, 10, 11),
            end_date=date(2026, 10, 15),
            status=self.order_status_completed,
        )
        # Lender reviewing borrower on this order
        Review.objects.create(
            order=order,
            reviewer=self.owner,
            rating=5,
            comment="Borrower returned the item in great condition.",
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should NOT appear as a listing review
        self.assertEqual(response.data["reviews"], [])
        # Owner hasn't received reviews as a lender yet
        self.assertIsNone(response.data["lender"]["rating_average"])
        self.assertEqual(response.data["lender"]["total_reviews"], 0)

    def test_retrieve_listing_lender_stats_aggregate_across_all_listings(self):
        """Lender profile summary aggregates reviews across all listings owned by the lender."""
        # Create a second listing owned by the same lender
        second_listing = Listing.objects.create(
            lender=self.owner,
            title="Scientific Calculator fx-991EX",
            description="High precision calculator.",
            category=self.category,
            condition="Like New",
            pickup_location=self.pickup_location,
            rate_per_day=Decimal("15.00"),
            is_ownership_confirmed=True,
            status=self.status_active,
        )

        # Order + review on the second listing
        order_second_listing = Order.objects.create(
            listing=second_listing,
            borrower=self.other_user,
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 14),
            status=self.order_status_completed,
        )
        Review.objects.create(
            order=order_second_listing,
            reviewer=self.other_user,
            rating=4,
            comment="Calculator worked properly.",
        )

        # When viewing the FIRST listing:
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        # Listing 1 has no reviews of its own
        self.assertEqual(data["reviews"], [])
        # But lender's profile summary reflects their overall reputation (1 review, avg 4.0)
        self.assertEqual(data["lender"]["rating_average"], 4.0)
        self.assertEqual(data["lender"]["total_reviews"], 1)

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
