"""Tests for mutual reviews and ratings after order completion (CP-601)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.constants import REVIEW_WINDOW_DAYS
from apps.core.models import SystemConfig
from apps.listings.models import (
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.constants import NOTIFICATION_TYPE_NEW_REVIEW
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus
from apps.reviews.models import Review
from apps.users.models import User


class ReviewSubmissionTests(TestCase):
    """Test suite for CP-601 mutual review submission, 7-day window, and rating recalculation."""

    def setUp(self) -> None:
        self.client = APIClient()

        self.lender = User.objects.create_user(
            email="lender_cp601@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender One",
            contact_number="09171112222",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.borrower = User.objects.create_user(
            email="borrower_cp601@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower One",
            contact_number="09173334444",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.outsider = User.objects.create_user(
            email="outsider_cp601@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Outsider User",
            contact_number="09175556666",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Electronics")
        self.pickup_location, _ = PickupLocation.objects.get_or_create(
            name="CEA Building",
            defaults={"description": "Lobby"},
        )
        self.listing_active, _ = ListingStatus.objects.get_or_create(name="active")
        self.listing = Listing.objects.create(
            lender=self.lender,
            category=self.category,
            pickup_location=self.pickup_location,
            status=self.listing_active,
            title="Scientific Calculator FX-991EX",
            description="Good condition calculator",
            condition="good",
            rate_per_day=Decimal("50.00"),
            is_ownership_confirmed=True,
        )

        self.status_completed, _ = OrderStatus.objects.get_or_create(name="completed")
        self.status_active, _ = OrderStatus.objects.get_or_create(name="active")
        self.status_returned, _ = OrderStatus.objects.get_or_create(name="returned")

        self.order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            status=self.status_completed,
        )

    def test_borrower_and_lender_can_each_review_completed_order_once(self) -> None:
        """Both borrower and lender can submit one review each, updating counterparty ratings."""
        self.client.force_authenticate(user=self.borrower)
        resp_b = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 5, "comment": "Great lender, smooth handover!"},
            format="json",
        )
        self.assertEqual(resp_b.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp_b.data["order_id"], self.order.pk)
        self.assertEqual(resp_b.data["reviewer_id"], self.borrower.pk)
        self.assertEqual(resp_b.data["reviewee_id"], self.lender.pk)
        self.assertEqual(resp_b.data["rating"], 5)
        self.assertEqual(resp_b.data["reviewee_average_rating"], 5.0)
        self.assertEqual(resp_b.data["reviewee_review_count"], 1)
        self.assertFalse(resp_b.data["can_report"])
        self.assertEqual(
            resp_b.data["report_url"],
            f"/api/v1/reviews/{resp_b.data['id']}/report/",
        )

        # Notification sent to lender
        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_NEW_REVIEW,
            ).exists()
        )

        # Lender can also submit one review for borrower on the same order
        self.client.force_authenticate(user=self.lender)
        resp_l = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 4, "comment": "Returned on time and in good shape."},
            format="json",
        )
        self.assertEqual(resp_l.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp_l.data["reviewer_id"], self.lender.pk)
        self.assertEqual(resp_l.data["reviewee_id"], self.borrower.pk)
        self.assertEqual(resp_l.data["reviewee_average_rating"], 4.0)
        self.assertEqual(resp_l.data["reviewee_review_count"], 1)

        # Listing order reviews shows both reviews and can_report=True for the counterparty's review
        list_resp = self.client.get(f"/api/v1/orders/{self.order.pk}/reviews/")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_resp.data), 2)
        borrower_review_payload = next(
            r for r in list_resp.data if r["reviewer_id"] == self.borrower.pk
        )
        self.assertTrue(borrower_review_payload["can_report"])

    def test_duplicate_review_by_same_party_is_rejected(self) -> None:
        """A user cannot submit more than one review per order."""
        self.client.force_authenticate(user=self.borrower)
        first = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 5, "comment": "First review"},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 3, "comment": "Second attempt"},
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Review.objects.filter(order=self.order).count(), 1)

    def test_review_recalculates_average_rating_across_multiple_orders(self) -> None:
        """Reviewed user's average rating is recalculated accurately when new reviews arrive."""
        order2 = Order.objects.create(
            listing=self.listing,
            borrower=self.outsider,
            start_date=date(2026, 11, 6),
            end_date=date(2026, 11, 8),
            status=self.status_completed,
        )

        self.client.force_authenticate(user=self.borrower)
        self.client.post(
            "/api/v1/reviews/",
            {"order_id": self.order.pk, "rating": 5, "comment": "Five stars"},
            format="json",
        )

        self.client.force_authenticate(user=self.outsider)
        resp2 = self.client.post(
            "/api/v1/reviews/",
            {"order_id": order2.pk, "rating": 2, "comment": "Two stars"},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp2.data["reviewee_average_rating"], 3.5)
        self.assertEqual(resp2.data["reviewee_review_count"], 2)

        user_reviews = self.client.get(f"/api/v1/users/{self.lender.pk}/reviews/")
        self.assertEqual(user_reviews.status_code, status.HTTP_200_OK)
        self.assertEqual(user_reviews.data["average_rating"], 3.5)
        self.assertEqual(user_reviews.data["review_count"], 2)
        self.assertEqual(len(user_reviews.data["results"]), 2)

    def test_seven_day_submission_window_and_immutable_completed_at(self) -> None:
        """Reviews after the 7-day completion window are rejected even if order.updated_at is bumped."""
        eight_days_ago = timezone.now() - timedelta(days=8)
        Order.objects.filter(pk=self.order.pk).update(completed_at=eight_days_ago)
        self.order.refresh_from_db()

        # Touching the order bumps updated_at to now, but completed_at remains 8 days ago
        self.order.cancel_reason = "admin audit note"
        self.order.save()
        self.assertEqual(self.order.completed_at, eight_days_ago)

        self.client.force_authenticate(user=self.borrower)
        resp = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 4, "comment": "Too late"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expired", str(resp.data).lower())

    def test_custom_system_config_review_window_days_is_respected(self) -> None:
        """SystemConfig review_window_days overrides the default 7-day window."""
        SystemConfig.objects.update_or_create(
            config_key=REVIEW_WINDOW_DAYS,
            defaults={"config_value": "3"},
        )
        four_days_ago = timezone.now() - timedelta(days=4)
        Order.objects.filter(pk=self.order.pk).update(completed_at=four_days_ago)

        self.client.force_authenticate(user=self.borrower)
        resp = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("3-day", str(resp.data))

    def test_non_completed_order_cannot_be_reviewed(self) -> None:
        """Orders in active or returned status cannot be reviewed until completed."""
        active_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 12),
            status=self.status_active,
        )
        self.client.force_authenticate(user=self.borrower)
        resp = self.client.post(
            f"/api/v1/orders/{active_order.pk}/reviews/",
            {"rating": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_participant_cannot_review_or_view_order_reviews(self) -> None:
        """Users who are neither borrower nor lender receive 403 Forbidden."""
        self.client.force_authenticate(user=self.outsider)
        post_resp = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 1, "comment": "Not my order"},
            format="json",
        )
        self.assertEqual(post_resp.status_code, status.HTTP_403_FORBIDDEN)

        get_resp = self.client.get(f"/api/v1/orders/{self.order.pk}/reviews/")
        self.assertEqual(get_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_order_detail_exposes_review_eligibility_fields(self) -> None:
        """OrderDetailSerializer includes can_review, has_reviewed, and review_deadline."""
        self.client.force_authenticate(user=self.borrower)
        before_resp = self.client.get(f"/api/v1/orders/{self.order.pk}/")
        self.assertEqual(before_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(before_resp.data["can_review"])
        self.assertFalse(before_resp.data["has_reviewed"])
        self.assertIsNotNone(before_resp.data["review_deadline"])

        self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 5, "comment": "Great!"},
            format="json",
        )

        after_resp = self.client.get(f"/api/v1/orders/{self.order.pk}/")
        self.assertEqual(after_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(after_resp.data["can_review"])
        self.assertTrue(after_resp.data["has_reviewed"])

    def test_review_report_link_creates_open_review_report(self) -> None:
        """CP-601 <-> CP-901: Counterparty can report a review via report_url."""
        self.client.force_authenticate(user=self.borrower)
        create_resp = self.client.post(
            f"/api/v1/orders/{self.order.pk}/reviews/",
            {"rating": 1, "comment": "Unfair comment"},
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        review_id = create_resp.data["id"]
        report_url = create_resp.data["report_url"]

        self.client.force_authenticate(user=self.lender)
        detail_before = self.client.get(f"/api/v1/reviews/{review_id}/")
        self.assertEqual(detail_before.status_code, status.HTTP_200_OK)
        self.assertTrue(detail_before.data["can_report"])

        report_resp = self.client.post(
            report_url,
            {"category": "fake_review", "description": "Inaccurate claim"},
            format="json",
        )
        self.assertEqual(report_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(report_resp.data["status"], "open")
        self.assertEqual(report_resp.data["target_review_id"], review_id)

        detail_after = self.client.get(f"/api/v1/reviews/{review_id}/")
        self.assertFalse(detail_after.data["can_report"])

    def test_singular_order_review_endpoint(self) -> None:
        """GET /orders/<id>/review/ returns 404 before review and 200 with review object after review."""
        self.client.force_authenticate(user=self.borrower)
        get_before = self.client.get(f"/api/v1/orders/{self.order.pk}/review/")
        self.assertEqual(get_before.status_code, status.HTTP_404_NOT_FOUND)

        post_resp = self.client.post(
            f"/api/v1/orders/{self.order.pk}/review/",
            {"rating": 5, "comment": "Excellent experience"},
            format="json",
        )
        self.assertEqual(post_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(post_resp.data["rating"], 5)

        get_after = self.client.get(f"/api/v1/orders/{self.order.pk}/review/")
        self.assertEqual(get_after.status_code, status.HTTP_200_OK)
        self.assertEqual(get_after.data["id"], post_resp.data["id"])
        self.assertEqual(get_after.data["comment"], "Excellent experience")
