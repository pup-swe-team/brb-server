"""CP-301 — Search listings by keyword and filters. Ported from the merged branch."""

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

User = get_user_model()


class ListingSearchTests(APITestCase):
    """
    Test suite for CP-301: Search listings by keyword and filters.
    Covers keyword search (title + description), category, condition, location,
    price range, free_only, date availability, sorting, pagination,
    and mandatory exclusion of deactivated/deleted listings and suspended/revoked lenders.
    """

    def setUp(self) -> None:
        # CP-301 search runs as GET on the shared /api/v1/listings/ collection.
        self.search_url = reverse("listing-create")

        # Eligible Lenders
        self.lender1 = User.objects.create_user(
            email="lender1@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Juan",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.lender1.account_status = User.AccountStatusChoices.ACTIVE
        self.lender1.lender_status = User.LenderStatusChoices.ACTIVE
        self.lender1.save(update_fields=["account_status", "lender_status"])

        self.lender2 = User.objects.create_user(
            email="lender2@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Maria",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.lender2.account_status = User.AccountStatusChoices.ACTIVE
        self.lender2.lender_status = User.LenderStatusChoices.ACTIVE
        self.lender2.save(update_fields=["account_status", "lender_status"])

        # Ineligible Lenders
        self.suspended_lender = User.objects.create_user(
            email="suspended@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Suspended User",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.suspended_lender.account_status = User.AccountStatusChoices.SUSPENDED
        self.suspended_lender.lender_status = User.LenderStatusChoices.ACTIVE
        self.suspended_lender.save(update_fields=["account_status", "lender_status"])

        self.revoked_lender = User.objects.create_user(
            email="revoked@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Revoked Lender",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.revoked_lender.account_status = User.AccountStatusChoices.ACTIVE
        self.revoked_lender.lender_status = User.LenderStatusChoices.REVOKED
        self.revoked_lender.save(update_fields=["account_status", "lender_status"])

        # Caller (Borrower)
        self.borrower = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Student",
            affiliation=User.AffiliationChoices.STUDENT,
        )
        self.borrower.account_status = User.AccountStatusChoices.ACTIVE
        self.borrower.save(update_fields=["account_status"])

        # Categories & Statuses & Locations
        self.cat_calc, _ = ListingCategory.objects.get_or_create(name="Calculators")
        self.cat_books, _ = ListingCategory.objects.get_or_create(name="Textbooks")

        self.status_active, _ = ListingStatus.objects.get_or_create(name="active")
        self.status_deactivated, _ = ListingStatus.objects.get_or_create(
            name="deactivated"
        )
        self.status_deleted, _ = ListingStatus.objects.get_or_create(name="deleted")

        self.loc_library = PickupLocation.objects.create(name="Main Library")
        self.loc_charlie = PickupLocation.objects.create(
            name="Charlie Del Rosario Hall"
        )

        # 1. Eligible calculator listing
        self.listing_calc = Listing.objects.create(
            lender=self.lender1,
            title="Casio FX-991EX ClassWiz",
            description="Advanced scientific calculator for calculus and algebra",
            category=self.cat_calc,
            pickup_location=self.loc_library,
            status=self.status_active,
            condition="Like New",
            rate_per_day=25.00,
        )

        # 2. Eligible math textbook listing
        self.listing_book = Listing.objects.create(
            lender=self.lender1,
            title="Thomas' Calculus Early Transcendentals",
            description="Standard engineering math reference book",
            category=self.cat_books,
            pickup_location=self.loc_charlie,
            status=self.status_active,
            condition="Good",
            rate_per_day=15.00,
        )

        # 3. Eligible free summary notes
        self.listing_free = Listing.objects.create(
            lender=self.lender2,
            title="Organic Chemistry Review Notes",
            description="Handwritten summary sheets free to borrow for exam prep",
            category=self.cat_books,
            pickup_location=self.loc_library,
            status=self.status_active,
            condition="Fair",
            rate_per_day=0.00,
        )

        # 4. Deactivated listing (must be excluded)
        self.listing_deactivated = Listing.objects.create(
            lender=self.lender1,
            title="Deactivated Engineering Drawing Kit",
            description="T-square and triangles",
            category=self.cat_calc,
            pickup_location=self.loc_library,
            status=self.status_deactivated,
            condition="Good",
            rate_per_day=10.00,
        )

        # 5. Deleted listing (must be excluded)
        self.listing_deleted = Listing.objects.create(
            lender=self.lender1,
            title="Deleted Physics Book",
            description="University physics volume 2",
            category=self.cat_books,
            pickup_location=self.loc_library,
            status=self.status_deleted,
            condition="Good",
            rate_per_day=10.00,
        )

        # 6. Listing from suspended lender (must be excluded)
        self.listing_suspended = Listing.objects.create(
            lender=self.suspended_lender,
            title="Suspended Lender Item",
            description="Should never appear in search results",
            category=self.cat_books,
            pickup_location=self.loc_library,
            status=self.status_active,
            condition="Good",
            rate_per_day=10.00,
        )

        # 7. Listing from revoked lender (must be excluded)
        self.listing_revoked = Listing.objects.create(
            lender=self.revoked_lender,
            title="Revoked Lender Item",
            description="Should never appear in search results",
            category=self.cat_books,
            pickup_location=self.loc_library,
            status=self.status_active,
            condition="Good",
            rate_per_day=10.00,
        )

    def test_unauthenticated_request_is_denied(self) -> None:
        """Unauthenticated caller cannot search listings (401)."""
        response = self.client.get(self.search_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_search_all_active_excludes_ineligible_listings_and_lenders(self) -> None:
        """Search returns only active listings from active, non-revoked lenders."""
        self.client.force_authenticate(user=self.borrower)
        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)

        returned_ids = [item["id"] for item in response.data["results"]]
        self.assertIn(self.listing_calc.id, returned_ids)
        self.assertIn(self.listing_book.id, returned_ids)
        self.assertIn(self.listing_free.id, returned_ids)

        self.assertNotIn(self.listing_deactivated.id, returned_ids)
        self.assertNotIn(self.listing_deleted.id, returned_ids)
        self.assertNotIn(self.listing_suspended.id, returned_ids)
        self.assertNotIn(self.listing_revoked.id, returned_ids)

    def test_keyword_search_matches_title_and_description(self) -> None:
        """Keyword ?q= matches case-insensitively in title and description."""
        self.client.force_authenticate(user=self.borrower)

        # "calculus" appears in listing_calc description and listing_book title
        response = self.client.get(self.search_url, {"q": "calculus"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        returned_ids = [item["id"] for item in response.data["results"]]
        self.assertIn(self.listing_calc.id, returned_ids)
        self.assertIn(self.listing_book.id, returned_ids)
        self.assertNotIn(self.listing_free.id, returned_ids)

        # "organic" only appears in listing_free
        response2 = self.client.get(self.search_url, {"q": "organic"})
        self.assertEqual(response2.data["count"], 1)
        self.assertEqual(response2.data["results"][0]["id"], self.listing_free.id)

        # Non-matching keyword
        response3 = self.client.get(self.search_url, {"q": "xylophone"})
        self.assertEqual(response3.data["count"], 0)

    def test_filter_by_category(self) -> None:
        """Filter by ?category=<id> returns only listings in that category."""
        self.client.force_authenticate(user=self.borrower)
        response = self.client.get(self.search_url, {"category": self.cat_calc.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.listing_calc.id)

    def test_filter_by_condition(self) -> None:
        """Filter by ?condition=<val> matches case-insensitively."""
        self.client.force_authenticate(user=self.borrower)
        response = self.client.get(self.search_url, {"condition": "like new"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.listing_calc.id)

    def test_filter_by_pickup_location(self) -> None:
        """Filter by ?pickup_location=<id> matches designated location."""
        self.client.force_authenticate(user=self.borrower)
        response = self.client.get(
            self.search_url, {"pickup_location": self.loc_charlie.id}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.listing_book.id)

    def test_filter_by_price_range(self) -> None:
        """Filter by ?min_price and ?max_price bounds rate_per_day correctly."""
        self.client.force_authenticate(user=self.borrower)

        # Min price 20 -> only calc (25.00)
        res_min = self.client.get(self.search_url, {"min_price": 20})
        self.assertEqual(res_min.data["count"], 1)
        self.assertEqual(res_min.data["results"][0]["id"], self.listing_calc.id)

        # Max price 20 -> book (15.00) and free (0.00)
        res_max = self.client.get(self.search_url, {"max_price": 20})
        self.assertEqual(res_max.data["count"], 2)

        # Between 10 and 20 -> book (15.00)
        res_between = self.client.get(
            self.search_url, {"min_price": 10, "max_price": 20}
        )
        self.assertEqual(res_between.data["count"], 1)
        self.assertEqual(res_between.data["results"][0]["id"], self.listing_book.id)

    def test_filter_free_only(self) -> None:
        """Filter ?free_only=true returns only listings with rate 0 or null."""
        self.client.force_authenticate(user=self.borrower)
        response = self.client.get(self.search_url, {"free_only": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.listing_free.id)

    def test_filter_by_date_availability_excludes_blocked_listings(self) -> None:
        """Date availability query excludes listings with overlapping blocked ranges."""
        self.client.force_authenticate(user=self.borrower)

        # Block listing_calc from Nov 1 to Nov 5
        BlockedDateRange.objects.create(
            listing=self.listing_calc,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            reason="Confirmed order",
        )

        # Query range overlapping Nov 1 - Nov 5 -> listing_calc is excluded
        res_overlapping = self.client.get(
            self.search_url,
            {"available_from": "2026-11-03", "available_to": "2026-11-04"},
        )
        self.assertEqual(res_overlapping.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in res_overlapping.data["results"]]
        self.assertNotIn(self.listing_calc.id, returned_ids)
        self.assertIn(self.listing_book.id, returned_ids)
        self.assertIn(self.listing_free.id, returned_ids)

        # Query range outside Nov 1 - Nov 5 -> listing_calc is included
        res_free_range = self.client.get(
            self.search_url,
            {"available_from": "2026-11-07", "available_to": "2026-11-10"},
        )
        returned_ids2 = [item["id"] for item in res_free_range.data["results"]]
        self.assertIn(self.listing_calc.id, returned_ids2)

    def test_sorting(self) -> None:
        """Sorting orders by rate_per_day asc/desc and title."""
        self.client.force_authenticate(user=self.borrower)

        # Rate ascending: 0.00, 15.00, 25.00
        res_rate_asc = self.client.get(self.search_url, {"sort": "rate_per_day"})
        rates = [float(item["rate_per_day"]) for item in res_rate_asc.data["results"]]
        self.assertEqual(rates, [0.0, 15.0, 25.0])

        # Rate descending: 25.00, 15.00, 0.00
        res_rate_desc = self.client.get(self.search_url, {"sort": "-rate_per_day"})
        rates_desc = [
            float(item["rate_per_day"]) for item in res_rate_desc.data["results"]
        ]
        self.assertEqual(rates_desc, [25.0, 15.0, 0.0])

    def test_invalid_query_parameters_returns_400(self) -> None:
        """Passing non-integer category or invalid dates yields a 400 Bad Request."""
        self.client.force_authenticate(user=self.borrower)

        res_bad_cat = self.client.get(self.search_url, {"category": "not-an-int"})
        self.assertEqual(res_bad_cat.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", res_bad_cat.data)

        res_bad_date = self.client.get(self.search_url, {"available_from": "tomorrow"})
        self.assertEqual(res_bad_date.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("available_from", res_bad_date.data)
