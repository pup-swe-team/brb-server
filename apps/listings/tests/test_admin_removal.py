from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.listings.tests.base import BaseListingTestCase
from apps.orders.models import Order, OrderStatus
from apps.reports.models import ReviewReport, ReviewReportCategory
from apps.reviews.models import Review


class AdminRemovalTests(BaseListingTestCase):
    def setUp(self):
        super().setUp()
        self.listing_url = reverse("api-admin-remove-listing", args=[self.listing.pk])
        self.review_order = self.make_order("completed")
        self.review = Review.objects.create(
            order=self.review_order,
            reviewer=self.other_user,
            rating=5,
            comment="Excellent calculator",
        )
        self.review_url = reverse("api-admin-remove-review", args=[self.review.pk])

    def make_order(self, status_name):
        order_status, _ = OrderStatus.objects.get_or_create(name=status_name)
        return Order.objects.create(
            listing=self.listing,
            borrower=self.other_user,
            start_date=timezone.localdate() + timedelta(days=2),
            end_date=timezone.localdate() + timedelta(days=3),
            status=order_status,
        )

    def test_only_staff_can_remove_content(self):
        for url in (self.listing_url, self.review_url):
            self.client.force_authenticate(user=None)
            self.assertIn(self.client.delete(url).status_code, (401, 403))
            for user in (self.owner, self.other_user):
                self.client.force_authenticate(user=user)
                self.assertEqual(self.client.delete(url).status_code, 403)
        self.listing.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.listing.status.name, "active")
        self.assertIsNone(self.review.deleted_at)

    def test_admin_removes_listing_with_open_order_and_preserves_history(self):
        active_order = self.make_order("confirmed")
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.delete(self.listing_url).status_code, 204)
        self.listing.refresh_from_db()
        active_order.refresh_from_db()
        self.assertEqual(self.listing.status.name, "deleted")
        self.assertEqual(active_order.status.name, "confirmed")
        self.assertEqual(self.client.delete(self.listing_url).status_code, 204)

        self.client.force_authenticate(user=self.other_user)
        result = self.client.get(reverse("listing-create"))
        self.assertNotIn(self.listing.pk, {row["id"] for row in result.data["results"]})
        self.assertEqual(
            self.client.get(
                reverse("listing-detail", args=[self.listing.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("order-detail", args=[active_order.pk])
            ).status_code,
            200,
        )

        self.client.force_authenticate(user=self.owner)
        self.assertEqual(
            self.client.get(
                reverse("listing-detail", args=[self.listing.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("listing-reactivate", args=[self.listing.pk])
            ).status_code,
            400,
        )

    def test_owner_delete_still_blocks_on_open_order(self):
        self.make_order("confirmed")
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(
            self.client.delete(
                reverse("listing-detail", args=[self.listing.pk])
            ).status_code,
            400,
        )
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status.name, "active")

    def test_admin_removes_review_from_public_content_and_ratings(self):
        category = ReviewReportCategory.objects.create(name="Inappropriate")
        report = ReviewReport.objects.create(
            reporter=self.owner,
            target_review=self.review,
            category=category,
            description="Rule violation",
        )
        self.client.force_authenticate(user=self.other_user)
        detail_url = reverse("listing-detail", args=[self.listing.pk])
        before = self.client.get(detail_url).data
        self.assertEqual(len(before["reviews"]), 1)
        self.assertEqual(before["lender"]["total_reviews"], 1)

        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.delete(self.review_url).status_code, 204)
        self.review.refresh_from_db()
        self.assertIsNotNone(self.review.deleted_at)
        removed_at = self.review.deleted_at
        self.assertEqual(self.client.delete(self.review_url).status_code, 204)
        self.review.refresh_from_db()
        self.assertEqual(self.review.deleted_at, removed_at)
        self.assertTrue(ReviewReport.objects.filter(pk=report.pk).exists())

        self.client.force_authenticate(user=self.other_user)
        after = self.client.get(detail_url).data
        self.assertEqual(after["reviews"], [])
        self.assertEqual(after["lender"]["total_reviews"], 0)
        self.assertIsNone(after["lender"]["rating_average"])
        lender = self.client.get(reverse("lender-profile", args=[self.owner.pk])).data
        self.assertEqual(lender["review_count"], 0)

    def test_missing_ids_return_404_and_session_admin_can_remove(self):
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(
            self.client.delete(
                reverse("api-admin-remove-listing", args=[999999])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                reverse("api-admin-remove-review", args=[999999])
            ).status_code,
            404,
        )
        self.client.force_authenticate(user=None)
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.delete(self.review_url).status_code, 204)
