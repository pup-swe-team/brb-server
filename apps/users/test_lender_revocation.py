from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus

from .models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    LenderRevocation,
    User,
)
from .services import clear_lender_reapplication_hold
from .tests import PNG_BYTES, make_user


class LenderFixture:
    def setUp(self):
        super().setUp()
        self.lender = make_user("lender-revoke@iskolarngbayan.pup.edu.ph")
        self.lender.lender_status = User.LenderStatusChoices.ACTIVE
        self.lender.save(update_fields=["lender_status"])
        self.borrower = make_user("borrower-revoke@iskolarngbayan.pup.edu.ph")
        self.admin = make_user("revoke-admin@pup.edu.ph", is_staff=True)
        self.category = ListingCategory.objects.create(name="Calculators")
        self.location = PickupLocation.objects.create(name="Library")
        self.active, _ = ListingStatus.objects.get_or_create(name="active")
        self.listing = self.make_listing()
        self.requested = self.make_order("requested")
        self.self_url = reverse("auth-revoke-lender")
        self.admin_url = reverse("api-admin-revoke-lender", args=[self.lender.pk])

    def make_listing(self):
        return Listing.objects.create(
            lender=self.lender,
            title="Calculator",
            description="Working calculator",
            category=self.category,
            pickup_location=self.location,
            condition="Good",
            status=self.active,
        )

    def make_order(self, status_name):
        order_status, _ = OrderStatus.objects.get_or_create(name=status_name)
        return Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            start_date=timezone.localdate() + timedelta(days=2),
            end_date=timezone.localdate() + timedelta(days=3),
            status=order_status,
        )

    def approve_identity(self):
        IdentityDocument.objects.create(
            user=self.lender,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="REVOKE-TEST-1",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="approved"),
            consent_given=True,
            consented_at=timezone.now(),
        )


class LenderRevocationTests(LenderFixture, APITestCase):
    def test_self_revoke_cascades_and_preserves_borrower_access(self):
        second = self.make_listing()
        other_lender = make_user("other-lender@iskolarngbayan.pup.edu.ph")
        other_lender.lender_status = User.LenderStatusChoices.ACTIVE
        other_lender.save(update_fields=["lender_status"])
        borrowed_listing = Listing.objects.create(
            lender=other_lender,
            title="Textbook",
            description="Reference book",
            category=self.category,
            pickup_location=self.location,
            condition="Good",
            status=self.active,
        )
        completed, _ = OrderStatus.objects.get_or_create(name="completed")
        borrowed_order = Order.objects.create(
            listing=borrowed_listing,
            borrower=self.lender,
            start_date=timezone.localdate() - timedelta(days=3),
            end_date=timezone.localdate() - timedelta(days=2),
            status=completed,
        )
        self.client.force_authenticate(self.lender)
        response = self.client.post(self.self_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.lender.refresh_from_db()
        self.requested.refresh_from_db()
        self.assertEqual(self.lender.lender_status, "revoked")
        self.assertFalse(self.lender.lender_reapplication_hold)
        self.assertTrue(self.lender.is_active)
        self.assertEqual(self.requested.status.name, "declined")
        self.assertEqual(self.requested.decline_reason, "Lender status revoked.")
        self.assertEqual(
            Notification.objects.get(user=self.borrower).type.name, "decline"
        )
        second.refresh_from_db()
        self.assertEqual(second.status.name, "deactivated")
        self.assertEqual(LenderRevocation.objects.get().source, "self")

        self.client.force_authenticate(self.borrower)
        search_ids = {
            item["id"]
            for item in self.client.get(reverse("listing-create")).data["results"]
        }
        self.assertNotIn(self.listing.pk, search_ids)
        self.assertNotIn(second.pk, search_ids)
        self.assertIn(borrowed_listing.pk, search_ids)
        self.assertEqual(
            self.client.get(
                reverse("listing-detail", args=[self.listing.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("order-detail", args=[self.requested.pk])
            ).status_code,
            200,
        )

        self.client.force_authenticate(self.lender)
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("order-detail", args=[borrowed_order.pk])
            ).status_code,
            200,
        )
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

    def test_confirmed_and_active_orders_block_both_paths_without_changes(self):
        for state in ("confirmed", "active"):
            blocking = self.make_order(state)
            for url, actor, data in (
                (self.self_url, self.lender, {}),
                (self.admin_url, self.admin, {"reason": "policy_violation"}),
            ):
                self.client.force_authenticate(actor)
                self.assertEqual(self.client.post(url, data).status_code, 409)
                self.lender.refresh_from_db()
                self.requested.refresh_from_db()
                self.assertEqual(self.lender.lender_status, "active")
                self.assertEqual(self.requested.status.name, "requested")
                self.assertEqual(Notification.objects.count(), 0)
            blocking.delete()

    def test_admin_reason_permissions_and_application_hold(self):
        self.client.force_authenticate(self.borrower)
        self.assertEqual(
            self.client.post(self.admin_url, {"reason": "other"}).status_code, 403
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self.admin_url, {}).status_code, 400)
        self.assertEqual(
            self.client.post(self.admin_url, {"reason": "made_up"}).status_code, 400
        )
        response = self.client.post(
            self.admin_url, {"reason": "other", "detail": "Repeated incidents"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.lender.refresh_from_db()
        self.assertTrue(self.lender.lender_reapplication_hold)
        record = LenderRevocation.objects.get()
        self.assertEqual(
            (record.actor, record.reason, record.detail),
            (self.admin, "other", "Repeated incidents"),
        )
        self.approve_identity()
        self.client.force_authenticate(self.lender)
        self.assertEqual(
            self.client.post(reverse("auth-apply-lender")).status_code, 400
        )
        self.assertTrue(
            clear_lender_reapplication_hold(user=self.lender, actor=self.admin)
        )
        self.assertEqual(
            self.client.post(reverse("auth-apply-lender")).status_code, 200
        )
        self.lender.refresh_from_db()
        self.assertEqual(self.lender.lender_status, "active")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status.name, "deactivated")

    def test_self_revoked_lender_can_reapply_after_verification(self):
        self.client.force_authenticate(self.lender)
        self.assertEqual(self.client.post(self.self_url).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("auth-apply-lender")).status_code, 400
        )
        self.approve_identity()
        self.assertEqual(
            self.client.post(reverse("auth-apply-lender")).status_code, 200
        )

    def test_notification_failure_rolls_back_cascade(self):
        self.client.force_authenticate(self.lender)
        with (
            patch(
                "apps.users.services.Notification.objects.bulk_create",
                side_effect=RuntimeError("failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(self.self_url)
        self.lender.refresh_from_db()
        self.requested.refresh_from_db()
        self.assertEqual(self.lender.lender_status, "active")
        self.assertEqual(self.requested.status.name, "requested")
        self.assertEqual(LenderRevocation.objects.count(), 0)

    def test_lender_cannot_accept_after_revocation(self):
        self.client.force_authenticate(self.lender)
        self.client.post(self.self_url)
        self.assertEqual(
            self.client.post(
                reverse("order-accept", args=[self.requested.pk])
            ).status_code,
            409,
        )


class LenderRevocationAdminActionTests(LenderFixture, APITestCase):
    def setUp(self):
        super().setUp()
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        self.client.force_authenticate(None)
        self.client.force_login(self.admin)
        self.changelist = reverse("admin:users_user_changelist")

    def action(self, name, *, confirmed=False, **extra):
        return self.client.post(
            self.changelist,
            {
                "action": name,
                "_selected_action": [self.lender.pk],
                **({"_revoke_confirmed": "1"} if confirmed else {}),
                **extra,
            },
        )

    def test_revoke_action_collects_reason_and_cascades(self):
        response = self.action("revoke_selected_lenders")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Repeated late returns")
        self.assertEqual(
            self.action(
                "revoke_selected_lenders",
                confirmed=True,
                reason="repeated_late_returns",
            ).status_code,
            302,
        )
        self.lender.refresh_from_db()
        self.requested.refresh_from_db()
        self.assertEqual(self.lender.lender_status, "revoked")
        self.assertEqual(self.requested.status.name, "declined")
        self.assertEqual(LenderRevocation.objects.get().reason, "repeated_late_returns")

    def test_clear_hold_action_preserves_reapplication_requirement(self):
        self.action("revoke_selected_lenders", confirmed=True, reason="other")
        self.action("clear_selected_lender_holds")
        self.lender.refresh_from_db()
        self.assertFalse(self.lender.lender_reapplication_hold)
        self.assertEqual(self.lender.lender_status, "revoked")

    def test_direct_admin_change_cannot_set_lender_status(self):
        response = self.client.get(
            reverse("admin:users_user_change", args=[self.lender.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="lender_status"')
