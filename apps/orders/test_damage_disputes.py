from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.audit.models import AdminAccessLog
from apps.chat.models import Conversation, Message
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.notifications.models import Notification
from apps.orders.models import (
    Dispute,
    DisputeEvidence,
    Order,
    OrderStatus,
    OrderStatusOverride,
)
from apps.reports.models import (
    ListingReport,
    ListingReportCategory,
    UserReport,
    UserReportCategory,
)
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

    def test_borrower_response_preserves_lender_description_and_invalid_state_rejected(
        self,
    ):
        # 1. Lender opens dispute (photo + video required per CP-903 / TC-093 / TC-094)
        self.client.force_authenticate(user=self.lender)
        url = reverse("order-damage-report", kwargs={"order_id": self.order.pk})
        lender_photo = SimpleUploadedFile(
            "damage_cover.jpg", b"photo-bytes", content_type="image/jpeg"
        )
        lender_video = SimpleUploadedFile(
            "damage_cover.mp4", b"video-bytes", content_type="video/mp4"
        )
        res1 = self.client.post(
            url,
            {
                "description": "Battery compartment door is missing",
                "evidence": [lender_photo, lender_video],
            },
            format="multipart",
        )
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # 2. Borrower posts response without attachments (optional per TC-095) -> description preserved
        self.client.force_authenticate(user=self.borrower)
        res2 = self.client.post(
            url,
            {"description": "It was already loose before handover"},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        data = res2.json()
        self.assertEqual(data["description"], "Battery compartment door is missing")
        self.assertEqual(
            data["borrower_response"], "It was already loose before handover"
        )

        # 3. Cancelled order cannot open a damage dispute -> 409 Conflict
        cancelled_status, _ = OrderStatus.objects.get_or_create(name="cancelled")
        cancelled_order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=self.today,
            end_date=self.today + timedelta(days=1),
            status=cancelled_status,
        )
        cancelled_url = reverse(
            "order-damage-report", kwargs={"order_id": cancelled_order.pk}
        )
        res3 = self.client.post(
            cancelled_url,
            {"description": "Should fail"},
            format="json",
        )
        self.assertEqual(res3.status_code, status.HTTP_409_CONFLICT)

    def test_dispute_dossier_links_chat_reports_and_logs_contact_release(self):
        conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.lender,
            order=self.order,
            listing=self.listing,
        )
        Message.objects.create(
            conversation=conv,
            sender=self.lender,
            content="Please return the missing cover.",
        )
        u_cat, _ = UserReportCategory.objects.get_or_create(name="scam_fraud")
        UserReport.objects.create(
            reporter=self.lender,
            target_user=self.borrower,
            order=self.order,
            category=u_cat,
            description="Returned damaged calculator",
            status="open",
        )
        l_cat, _ = ListingReportCategory.objects.get_or_create(name="prohibited")
        ListingReport.objects.create(
            reporter=self.borrower,
            target_listing=self.listing,
            category=l_cat,
            description="Misleading condition",
            status="open",
        )

        dispute = Dispute.objects.create(
            order=self.order,
            raised_by=self.lender,
            description="Cracked display",
            borrower_response="Dropped accidentally",
            status=Dispute.StatusChoices.OPEN,
        )
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(
            reverse("api-admin-dispute-detail", kwargs={"pk": dispute.pk})
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.json()
        self.assertEqual(body["case"]["borrower_response"], "Dropped accidentally")
        self.assertEqual(len(body["chat"]), 1)
        self.assertEqual(
            body["chat"][0]["messages"][0]["content"],
            "Please return the missing cover.",
        )
        self.assertEqual(len(body["reports"]), 2)
        self.assertEqual(
            AdminAccessLog.objects.filter(
                admin=self.admin, action="contact_release"
            ).count(),
            2,
        )

    def test_resolve_creates_override_audit_and_blocks_repeat_actions(self):
        disputed_status, _ = OrderStatus.objects.get_or_create(name="disputed")
        self.order.status = disputed_status
        self.order.save(update_fields=["status"])

        dispute = Dispute.objects.create(
            order=self.order,
            raised_by=self.lender,
            description="Missing stylus",
            status=Dispute.StatusChoices.OPEN,
        )
        self.client.force_authenticate(user=self.admin)
        resolve_url = reverse("api-admin-dispute-resolve", kwargs={"pk": dispute.pk})
        res = self.client.post(
            resolve_url,
            {"resolution_notes": "Replacement stylus provided"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["order_status"], "completed")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "completed")
        self.assertIsNotNone(self.order.completed_at)
        self.assertTrue(
            OrderStatusOverride.objects.filter(
                order=self.order,
                admin=self.admin,
                previous_status="disputed",
                new_status="completed",
            ).exists()
        )
        self.assertEqual(
            Notification.objects.filter(
                reference_id=str(self.order.pk),
                type__name="report_updates",
            ).count(),
            2,
        )

        # Repeat resolve or escalate on resolved dispute -> 409 Conflict
        repeat_res = self.client.post(resolve_url, {}, format="json")
        self.assertEqual(repeat_res.status_code, status.HTTP_409_CONFLICT)
        escalate_res = self.client.post(
            reverse("api-admin-dispute-escalate", kwargs={"pk": dispute.pk}),
            {},
            format="json",
        )
        self.assertEqual(escalate_res.status_code, status.HTTP_409_CONFLICT)

    def test_escalate_dispute_keeps_order_disputed_and_attaches_evidence(self):
        disputed_status, _ = OrderStatus.objects.get_or_create(name="disputed")
        self.order.status = disputed_status
        self.order.save(update_fields=["status"])

        dispute = Dispute.objects.create(
            order=self.order,
            raised_by=self.lender,
            description="Severe chassis crack",
            status=Dispute.StatusChoices.OPEN,
        )
        self.client.force_authenticate(user=self.admin)
        oss_photo = SimpleUploadedFile(
            "oss_report.jpg", b"oss-img", content_type="image/jpeg"
        )
        res = self.client.post(
            reverse("api-admin-dispute-escalate", kwargs={"pk": dispute.pk}),
            {
                "resolution_notes": "Referred to PUP OSS for mediation",
                "evidence": [oss_photo],
            },
            format="multipart",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["status"], "escalated")
        self.assertEqual(res.json()["order_status"], "disputed")

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.StatusChoices.ESCALATED)
        self.assertEqual(dispute.resolved_by, self.admin)
        self.assertEqual(DisputeEvidence.objects.filter(dispute=dispute).count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "disputed")

    def test_lender_damage_report_requires_both_photo_and_video_tc094(self):
        self.client.force_authenticate(user=self.lender)
        url = reverse("order-damage-report", kwargs={"order_id": self.order.pk})

        # 0 files -> 400
        no_files = self.client.post(
            url,
            {"description": "Damage with no attachments"},
            format="json",
        )
        self.assertEqual(no_files.status_code, status.HTTP_400_BAD_REQUEST)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "active")

        # Only photo, 0 videos (TC-094) -> 400
        only_photo = SimpleUploadedFile(
            "only_photo.jpg", b"photo-bytes", content_type="image/jpeg"
        )
        photo_only_res = self.client.post(
            url,
            {"description": "Missing video", "evidence": [only_photo]},
            format="multipart",
        )
        self.assertEqual(photo_only_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "active")

        # Only video, 0 photos -> 400
        only_video = SimpleUploadedFile(
            "only_video.mp4", b"video-bytes", content_type="video/mp4"
        )
        video_only_res = self.client.post(
            url,
            {"description": "Missing photo", "evidence": [only_video]},
            format="multipart",
        )
        self.assertEqual(video_only_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status.name, "active")

    def test_borrower_dispute_response_alias_and_dossier_client_fields(self):
        # Lender opens dispute on damage-report endpoint
        self.client.force_authenticate(user=self.lender)
        lender_photo = SimpleUploadedFile(
            "casing.jpg", b"photo-bytes", content_type="image/jpeg"
        )
        lender_video = SimpleUploadedFile(
            "casing.mp4", b"video-bytes", content_type="video/mp4"
        )
        open_res = self.client.post(
            reverse("order-damage-report", kwargs={"order_id": self.order.pk}),
            {
                "description": "Cracked casing on delivery return",
                "evidence": [lender_photo, lender_video],
            },
            format="multipart",
        )
        self.assertEqual(open_res.status_code, status.HTTP_201_CREATED)
        dispute_id = open_res.json()["id"]

        # Borrower responds using brb-client /orders/<id>/dispute-response/ endpoint
        self.client.force_authenticate(user=self.borrower)
        resp_photo = SimpleUploadedFile(
            "handover_ok.jpg", b"photo-bytes", content_type="image/jpeg"
        )
        resp = self.client.post(
            reverse("order-dispute-response", kwargs={"order_id": self.order.pk}),
            {
                "description": "Casing was intact when returned.",
                "evidence": [resp_photo],
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            resp.json()["description"], "Cracked casing on delivery return"
        )
        self.assertEqual(
            resp.json()["borrower_response"], "Casing was intact when returned."
        )

        # Dossier exposes both backend & AdminCaseScreen keys cleanly
        self.client.force_authenticate(user=self.admin)
        dossier_res = self.client.get(
            reverse("admin-dispute-detail", kwargs={"pk": dispute_id})
        )
        self.assertEqual(dossier_res.status_code, status.HTTP_200_OK)
        body = dossier_res.json()
        self.assertEqual(body["case"]["case_id"], f"DISP-{dispute_id}")
        self.assertEqual(len(body["case"]["evidence"]), 3)
        self.assertEqual(body["case"]["evidence"][0]["media_type"], "photo")
        self.assertIn("price_per_day", body["listing"])
        self.assertIn("pickup_location", body["order"])
