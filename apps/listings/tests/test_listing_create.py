import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status

from apps.listings.models import Listing, ListingPhoto, PickupLocation
from apps.listings.tests.base import BaseListingTestCase
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)


class ListingCreateViewTests(BaseListingTestCase):
    """Integration tests for the ListingCreateView endpoint (CP-401)."""

    def setUp(self):
        super().setUp()
        self.create_url = reverse("listing-create")

        # Set up identity document lookup tables
        self.status_approved, _ = IdentityDocumentStatus.objects.get_or_create(
            name="approved"
        )
        self.status_pending, _ = IdentityDocumentStatus.objects.get_or_create(
            name="pending"
        )
        self.doc_type_pup, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")

        # Grant verified identity to self.owner
        self._verify_user(self.owner)

    def _verify_user(self, user: User) -> IdentityDocument:
        """Helper to approve an identity document for a user."""
        return IdentityDocument.objects.create(
            user=user,
            document_type=self.doc_type_pup,
            id_number=f"ID-{user.id}",
            document_data=b"encrypted_identity_bytes",
            status=self.status_approved,
            consent_given=True,
            consented_at=timezone.now(),
        )

    def _create_test_image(
        self,
        name: str = "test.jpg",
        content_type: str = "image/jpeg",
        size: tuple[int, int] = (50, 50),
    ) -> SimpleUploadedFile:
        """Generate a valid in-memory image for upload tests."""
        file_obj = BytesIO()
        img = Image.new("RGB", size, color="blue")
        fmt = "PNG" if "png" in content_type else "JPEG"
        img.save(file_obj, format=fmt)
        file_obj.seek(0)
        return SimpleUploadedFile(name, file_obj.read(), content_type=content_type)

    # =========================================================================
    # Successful Creation Tests
    # =========================================================================

    def test_create_listing_success(self):
        """Verified lender can publish a listing with valid payload and photo."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image("item.jpg", "image/jpeg")

        tomorrow = timezone.now().date() + timedelta(days=1)
        next_week = tomorrow + timedelta(days=7)

        payload = {
            "title": "TI-84 Plus Graphing Calculator",
            "description": "Standard graphing calculator in pristine condition.",
            "category": self.category.id,
            "condition": "Like New",
            "pickup_location": self.pickup_location.id,
            "rate_per_day": "30.00",
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "availability_windows": json.dumps(
                [
                    {
                        "start_date": tomorrow.isoformat(),
                        "end_date": next_week.isoformat(),
                    }
                ]
            ),
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data

        self.assertEqual(data["title"], "TI-84 Plus Graphing Calculator")
        self.assertEqual(data["condition"], "Like New")
        self.assertEqual(Decimal(data["rate_per_day"]), Decimal("30.00"))
        self.assertTrue(data["is_ownership_confirmed"])
        self.assertEqual(data["status"]["name"], "active")
        self.assertEqual(data["lender"]["id"], self.owner.id)

        # Verify photo was created
        self.assertEqual(len(data["photos"]), 1)
        listing = Listing.objects.get(pk=data["id"])
        self.assertEqual(ListingPhoto.objects.filter(listing=listing).count(), 1)

        # Verify availability calendar window was created
        self.assertEqual(len(data["availability_windows"]), 1)
        self.assertEqual(
            data["availability_windows"][0]["start_date"], tomorrow.isoformat()
        )
        self.assertEqual(
            data["availability_windows"][0]["end_date"], next_week.isoformat()
        )

    def test_create_listing_flat_dates_success(self):
        """Verified lender can specify availability dates using start_date and end_date."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image("photo.png", "image/png")

        start_date = timezone.now().date() + timedelta(days=2)
        end_date = start_date + timedelta(days=5)

        payload = {
            "title": "Laboratory Coat (Small)",
            "description": "Clean white lab coat.",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["availability_windows"]), 1)
        self.assertEqual(
            response.data["availability_windows"][0]["start_date"],
            start_date.isoformat(),
        )

    # =========================================================================
    # Authorization & Permission Tests (Gate Checks)
    # =========================================================================

    def test_create_listing_unauthenticated_rejected(self):
        """Unauthenticated caller cannot create a listing."""
        response = self.client.post(self.create_url, data={})
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_create_listing_unverified_identity_rejected(self):
        """User without approved identity verification is blocked."""
        unverified_user = User.objects.create_user(
            email="unverified_lender@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Unverified User",
            contact_number="09111222333",
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        self.client.force_authenticate(user=unverified_user)

        response = self.client.post(self.create_url, data={})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Identity verification is required", str(response.data))

    def test_create_listing_non_lender_rejected(self):
        """User without active lender status is blocked even if identity is verified."""
        borrower_only = User.objects.create_user(
            email="verified_borrower@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Verified Borrower",
            contact_number="09111222334",
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.NONE,
        )
        self._verify_user(borrower_only)
        self.client.force_authenticate(user=borrower_only)

        response = self.client.post(self.create_url, data={})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Active lender status is required", str(response.data))

    def test_create_listing_suspended_lender_rejected(self):
        """User with suspended account is blocked from creating a listing."""
        suspended_lender = User.objects.create_user(
            email="suspended_lender@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Suspended Lender",
            contact_number="09111222335",
            account_status=User.AccountStatusChoices.SUSPENDED,
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        self._verify_user(suspended_lender)
        self.client.force_authenticate(user=suspended_lender)

        response = self.client.post(self.create_url, data={})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # =========================================================================
    # Validation Tests (Required Fields, Image Specs, Pickup Location)
    # =========================================================================

    def test_create_listing_requires_photos(self):
        """Listing creation fails when no photo is provided."""
        self.client.force_authenticate(user=self.owner)
        payload = {
            "title": "Physics Volume 1",
            "description": "Halliday Resnick Physics.",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)

    def test_create_listing_invalid_image_type_rejected(self):
        """Non-image or non-allowed content-type uploads are rejected."""
        self.client.force_authenticate(user=self.owner)
        pdf_file = SimpleUploadedFile(
            "document.pdf", b"%PDF-1.4 dummy", content_type="application/pdf"
        )

        payload = {
            "title": "Title",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [pdf_file],
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)

    def test_create_listing_oversized_image_rejected(self):
        """Images larger than 5MB are rejected."""
        self.client.force_authenticate(user=self.owner)
        large_content = b"0" * (5 * 1024 * 1024 + 1)
        oversized_file = SimpleUploadedFile(
            "huge.jpg", large_content, content_type="image/jpeg"
        )

        payload = {
            "title": "Title",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [oversized_file],
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)
        self.assertIn("5MB", str(response.data["photos"]))

    def test_create_listing_rejects_disguised_image_bytes(self):
        """Magic bytes decide the type: a PDF renamed to .png with an image/png
        header is still rejected."""
        self.client.force_authenticate(user=self.owner)
        disguised_file = SimpleUploadedFile(
            "fake.png", b"%PDF-1.4 pretending to be a photo", content_type="image/png"
        )

        payload = {
            "title": "Title",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [disguised_file],
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)
        self.assertEqual(ListingPhoto.objects.count(), 0)

    def test_create_listing_rejects_string_photo_values(self):
        """JSON payloads must upload real files; string values are rejected."""
        self.client.force_authenticate(user=self.owner)

        tomorrow = timezone.now().date() + timedelta(days=1)
        next_week = tomorrow + timedelta(days=7)
        payload = {
            "title": "Organic Chemistry",
            "description": "Reference copy available for borrowing.",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": ["https://example.com/photo.jpg"],
            "availability_windows": [
                {
                    "start_date": tomorrow.isoformat(),
                    "end_date": next_week.isoformat(),
                }
            ],
        }

        response = self.client.post(self.create_url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("photos", response.data)
        self.assertEqual(ListingPhoto.objects.count(), 0)

    def test_listing_photo_url_resolves_to_media_route(self):
        """Photo URLs are absolute under /media/, and the media route serves the file."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image("served.png", "image/png")

        tomorrow = timezone.now().date() + timedelta(days=1)
        next_week = tomorrow + timedelta(days=7)

        payload = {
            "title": "Campbell Biology",
            "description": "Borrowable reference copy in good condition.",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "availability_windows": json.dumps(
                [
                    {
                        "start_date": tomorrow.isoformat(),
                        "end_date": next_week.isoformat(),
                    }
                ]
            ),
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        photo_url = response.data["photos"][0]["file_reference"]
        self.assertTrue(photo_url.startswith("http://testserver/media/"))

        media_response = self.client.get(photo_url)
        self.assertEqual(media_response.status_code, status.HTTP_200_OK)
        self.assertTrue(media_response["Content-Type"].startswith("image/"))

    def test_create_listing_requires_ownership_confirmation(self):
        """Unconfirmed ownership statement is rejected."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image()

        payload = {
            "title": "Book",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": False,
            "photos": [test_photo],
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_ownership_confirmed", response.data)

    def test_create_listing_soft_deleted_pickup_location_rejected(self):
        """Selecting a soft-deleted pickup location fails validation."""
        self.client.force_authenticate(user=self.owner)
        deleted_location = PickupLocation.objects.create(
            name="Decommissioned Kiosk",
            deleted_at=timezone.now(),
        )
        test_photo = self._create_test_image()

        payload = {
            "title": "Book",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": deleted_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "start_date": "2026-10-15",
            "end_date": "2026-10-20",
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pickup_location", response.data)

    def test_create_listing_past_availability_dates_rejected(self):
        """Availability dates in the past are rejected."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image()

        yesterday = timezone.now().date() - timedelta(days=1)

        payload = {
            "title": "Book",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "start_date": yesterday.isoformat(),
            "end_date": yesterday.isoformat(),
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("availability_windows", response.data)

    def test_create_listing_inverted_availability_dates_rejected(self):
        """End date before start date is rejected."""
        self.client.force_authenticate(user=self.owner)
        test_photo = self._create_test_image()

        start = timezone.now().date() + timedelta(days=5)
        end = timezone.now().date() + timedelta(days=2)

        payload = {
            "title": "Book",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("availability_windows", response.data)

    # =========================================================================
    # Required-field contract
    #
    # The mobile form sends the category and the pickup location as foreign
    # keys, so the API only ever accepts the id. A client that cannot resolve
    # a name to an id (the lists failed to load, or a row was renamed) would
    # otherwise drop the field and the user would see a bare "This field is
    # required." These tests pin the contract down.
    # =========================================================================

    def _valid_payload(self, test_photo) -> dict:
        start = timezone.now().date() + timedelta(days=1)
        end = timezone.now().date() + timedelta(days=5)
        return {
            "title": "Book",
            "description": "Desc",
            "category": self.category.id,
            "condition": "Good",
            "pickup_location": self.pickup_location.id,
            "is_ownership_confirmed": True,
            "photos": [test_photo],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }

    def test_create_listing_requires_a_description(self):
        """A blank description is rejected: a listing always carries one."""
        self.client.force_authenticate(user=self.owner)
        payload = self._valid_payload(self._create_test_image())
        payload["description"] = ""

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", response.data)

    def test_create_listing_requires_a_category(self):
        """The category is mandatory and is addressed by id."""
        self.client.force_authenticate(user=self.owner)
        payload = self._valid_payload(self._create_test_image())
        payload.pop("category")

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", response.data)

    def test_create_listing_requires_a_pickup_location(self):
        """The pickup location is mandatory and is addressed by id."""
        self.client.force_authenticate(user=self.owner)
        payload = self._valid_payload(self._create_test_image())
        payload.pop("pickup_location")

        response = self.client.post(self.create_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pickup_location", response.data)
