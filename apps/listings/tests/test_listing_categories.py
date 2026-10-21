"""Read-only listing-category feed consumed by the client search/add-item UI."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.listings.models import ListingCategory

User = get_user_model()


class ListingCategoryListTests(APITestCase):
    """
    Test suite for the read-only category endpoint.

    Categories are curated data managed by administrators in /admin/ (and
    /portal/ later); the client only needs `id` and `name` to power the search
    filter and the Add-Item dropdown.
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

        self.textbooks = ListingCategory.objects.create(name="Textbooks")
        self.calculators = ListingCategory.objects.create(name="Calculators")

        self.list_url = reverse("listing-category-list")

    def test_unauthenticated_user_cannot_list_categories(self) -> None:
        """Unauthenticated caller is denied with 401."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_can_list_categories(self) -> None:
        """Any authenticated user can fetch categories for dropdowns."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        names = [item["name"] for item in response.data]
        self.assertIn("Textbooks", names)
        self.assertIn("Calculators", names)

    def test_categories_expose_only_id_and_name(self) -> None:
        """Categories never leak fields beyond the public id/name contract."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data)
        for item in response.data:
            self.assertEqual(set(item.keys()), {"id", "name"})

    def test_categories_are_ordered_by_name(self) -> None:
        """The feed is deterministically ordered by name."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        names = [item["name"] for item in response.data]
        self.assertEqual(names, sorted(names))

    def test_no_pagination_envelope(self) -> None:
        """The endpoint returns a flat list, not a paginated dict."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertIsInstance(response.data, list)

    def test_category_list_is_read_only(self) -> None:
        """POST is not allowed on the read-only category collection."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url, {"name": "Unauthorized"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
