from datetime import date
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.listings.models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.users.models import User


class BaseListingTestCase(APITestCase):
    """Base test case providing shared fixtures for listings tests."""

    def setUp(self):
        super().setUp()

        self.owner = User.objects.create_user(
            email="owner@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Owner Iskolar",
            contact_number="09123456789",
            lender_status=User.LenderStatusChoices.ACTIVE,
        )

        self.other_user = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Borrower Iskolar",
            contact_number="09987654321",
        )

        self.admin_user = User.objects.create_superuser(
            email="admin@pup.edu.ph",
            password="password123",
            full_name="Admin Faculty",
            contact_number="09112223344",
        )

        self.category = ListingCategory.objects.create(
            name="Textbooks",
            description="Course books and references",
        )

        self.status_active = ListingStatus.objects.create(
            name="active",
        )

        self.pickup_location = PickupLocation.objects.create(
            name="Main Campus Library",
            description="Second Floor Reference Section",
        )

        self.listing = Listing.objects.create(
            lender=self.owner,
            title="Calculus: Early Transcendentals",
            description="Complete calculus reference in good condition.",
            category=self.category,
            condition="Good",
            pickup_location=self.pickup_location,
            rate_per_day=Decimal("25.00"),
            is_ownership_confirmed=True,
            status=self.status_active,
        )

        self.availability_window = AvailabilityWindow.objects.create(
            listing=self.listing,
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 20),
        )
