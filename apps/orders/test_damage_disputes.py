from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.orders.models import Dispute, Order, OrderStatus
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)


class DamageReportAndDisputeTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.admin = User.objects.create_superuser(
            email="admin@pup.edu.ph",
            full_name="Admin User",
            contact_number="09111111111",
        )
        self.lender = User.objects.create_user(
            email="lender@iskolarngbayan.pup.edu.ph",
            full_name="Lender Juan",
            contact_number="09123456789",
        )
        self.borrower = User.objects.create_user(
            email="borrower@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Maria",
            contact_number="09987654321",
        )
        approved, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        for u in (self.lender, self.borrower):
            IdentityDocument.objects.create(
                user=u,
                document_type=doc_type,
                id_number=f"ID-{u.pk}",
                document_data=b"test",
                status=approved,
                consent_given=True,
                consented_at=timezone.now(),
            )
        self.cat = ListingCategory.objects.create(name="Calculators")
        self.loc = PickupLocation.objects.create(name="Main Gate")
        self.active_status = ListingStatus.objects.create(name="active")
        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Scientific Calculator",
            description="Good condition",
            category=self.cat,
            pickup_location=self.loc,
            status=self.active_status,
        )
        self.order_status, _ = OrderStatus.objects.get_or_create(name="active")
        self.order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=self.today - timedelta(days=3),
            end_date=self.today + timedelta(days=2),
            status=self.order_status,
        )

    def test_submit_damage_report_with_photos_and_videos(self):
        self.client.force_authenticate(user=self.lender)
        url = reverse("order-damage-report", kwargs={"order_id": self.order.pk})

        dummy_photo = SimpleUploadedFile(
            "crack.jpg", b"fake image content", content_type="image/jpeg"
        )
        dummy_video = SimpleUploadedFile(
            "demo.mp4", b"fake video content", content_type="video/mp4"
        )

        res = self.client.post(
            url,
            {
                "description": "Screen is cracked and case is broken",
                "evidence": [dummy_photo, dummy_video],
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data["order_id"], self.order.pk)
        self.assertEqual(data["description"], "Screen is cracked and case is broken")
        self.assertEqual(len(data["evidences"]), 2)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "disputed")

        # GET damage report by borrower
        self.client.force_authenticate(user=self.borrower)
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            get_res.json()["description"], "Screen is cracked and case is broken"
        )

    def test_admin_dispute_dossier_and_resolution(self):
        dispute = Dispute.objects.create(
            order=self.order,
            raised_by=self.lender,
            description="Missing accessories",
            status=Dispute.StatusChoices.OPEN,
        )
        self.client.force_authenticate(user=self.admin)

        # Admin lists disputes
        list_url = reverse("admin-dispute-list")
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_res.json()), 1)

        # Admin views dossier
        detail_url = reverse("admin-dispute-detail", kwargs={"pk": dispute.pk})
        detail_res = self.client.get(detail_url)
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        body = detail_res.json()
        self.assertIn("case", body)
        self.assertIn("order", body)
        self.assertIn("borrower", body)
        self.assertIn("lender", body)
        self.assertEqual(body["case"]["status"], "open")

        # Admin resolves dispute
        resolve_url = reverse("admin-dispute-resolve", kwargs={"pk": dispute.pk})
        resolve_res = self.client.post(
            resolve_url,
            {"resolution_notes": "Damages covered by borrower deposit"},
            format="json",
        )
        self.assertEqual(resolve_res.status_code, status.HTTP_200_OK)

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.StatusChoices.RESOLVED)
        self.assertEqual(
            dispute.resolution_notes, "Damages covered by borrower deposit"
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "completed")

    def test_handover_code_status_and_reuse_existing(self):
        # Set order to confirmed so handover code can be generated
        confirmed_status, _ = OrderStatus.objects.get_or_create(name="confirmed")
        self.order.status = confirmed_status
        self.order.save(update_fields=["status"])

        self.client.force_authenticate(user=self.lender)
        gen_url = reverse(
            "order-handover-code-generate", kwargs={"order_id": self.order.pk}
        )

        # 1. Generate code first time
        res1 = self.client.post(gen_url)
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        code_id_1 = res1.json()["id"]
        expires_at_1 = res1.json()["expires_at"]

        # 2. GET returns existing active code and timer without changing it
        get_res = self.client.get(gen_url)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertEqual(get_res.json()["has_active_code"], True)
        self.assertEqual(get_res.json()["expires_at"], expires_at_1)
        self.assertEqual(get_res.json()["is_locked_out"], False)

        # 3. POST with reuse_existing=true returns same code
        reuse_res = self.client.post(f"{gen_url}?reuse_existing=true")
        self.assertEqual(reuse_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reuse_res.json()["id"], code_id_1)
        self.assertEqual(reuse_res.json()["expires_at"], expires_at_1)

    def test_deactivate_returns_has_unsettled_orders_code(self):
        self.client.force_authenticate(user=self.borrower)
        deact_url = reverse("auth-deactivate")
        res = self.client.post(
            deact_url, {"password": "StrongPassword123!"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json().get("code"), "has_unsettled_orders")
        self.assertIn("open_orders", res.json())
