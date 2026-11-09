"""Automated tests for CP-801: Platform notifications and event triggers (FR11)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.chat.models import Conversation, Message
from apps.listings.models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.constants import (
    NOTIFICATION_TYPE_ACCEPTANCE,
    NOTIFICATION_TYPE_CANCELLATION,
    NOTIFICATION_TYPE_NEW_MESSAGE,
    NOTIFICATION_TYPE_NEW_REQUEST,
    NOTIFICATION_TYPE_NEW_REVIEW,
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
    NOTIFICATION_TYPE_VERIFICATION_RESULT,
)
from apps.notifications.models import (
    Notification,
)
from apps.notifications.services import (
    create_notification,
    get_user_notification_preferences,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    process_upcoming_due_date_notifications,
    update_user_notification_preferences,
)
from apps.orders.constants import ORDER_STATUS_ACTIVE
from apps.orders.models import Order, OrderStatus
from apps.orders.services import (
    cancel_order,
    process_overdue_and_unreturned_orders,
    request_borrow,
)
from apps.reviews.models import Review
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)


class NotificationServiceTests(TestCase):
    """Unit tests for notification service layer."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="service_user@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Service User",
            contact_number="09170000001",
        )
        self.other_user = User.objects.create_user(
            email="other_user@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Other User",
            contact_number="09170000002",
        )

    def test_create_and_deduplicate_notification(self) -> None:
        notif1 = create_notification(
            user=self.user,
            event_name=NOTIFICATION_TYPE_NEW_REQUEST,
            reference_id="101",
        )
        self.assertIsNotNone(notif1)
        self.assertEqual(notif1.user, self.user)
        self.assertEqual(notif1.type.name, NOTIFICATION_TYPE_NEW_REQUEST)
        self.assertEqual(notif1.reference_id, "101")
        self.assertFalse(notif1.is_read)

        # Idempotency: calling again with same unread event & reference returns existing
        notif2 = create_notification(
            user=self.user,
            event_name=NOTIFICATION_TYPE_NEW_REQUEST,
            reference_id="101",
        )
        self.assertEqual(notif1.pk, notif2.pk)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_mark_notification_as_read(self) -> None:
        notif = create_notification(
            user=self.user,
            event_name=NOTIFICATION_TYPE_ACCEPTANCE,
            reference_id="202",
        )
        self.assertFalse(notif.is_read)

        updated = mark_notification_as_read(notification_id=notif.pk, user=self.user)
        self.assertTrue(updated.is_read)

        # Reload from database
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_notifications_as_read(self) -> None:
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="1"
        )
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_ACCEPTANCE, reference_id="2"
        )
        create_notification(
            user=self.other_user,
            event_name=NOTIFICATION_TYPE_NEW_REQUEST,
            reference_id="3",
        )

        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(), 2
        )

        marked = mark_all_notifications_as_read(user=self.user)
        self.assertEqual(marked, 2)
        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(), 0
        )
        # Other user's notification remains unread
        self.assertEqual(
            Notification.objects.filter(user=self.other_user, is_read=False).count(), 1
        )

    def test_preference_opt_out_suppresses_in_app(self) -> None:
        # Opt out of request updates
        update_user_notification_preferences(
            user=self.user,
            new_prefs={"requests": {"push": False, "email": False}},
        )

        notif = create_notification(
            user=self.user,
            event_name=NOTIFICATION_TYPE_NEW_REQUEST,
            reference_id="303",
        )
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)

    def test_security_notifications_cannot_be_opted_out(self) -> None:
        # Attempt to disable security
        update_user_notification_preferences(
            user=self.user,
            new_prefs={"security": {"push": False, "email": False}},
        )
        prefs = get_user_notification_preferences(self.user)
        self.assertTrue(prefs["security"]["push"])
        self.assertTrue(prefs["security"]["email"])

        notif = create_notification(
            user=self.user,
            event_name=NOTIFICATION_TYPE_VERIFICATION_RESULT,
            reference_id="doc_1",
        )
        self.assertIsNotNone(notif)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)


class NotificationAPITests(APITestCase):
    """API endpoint tests for notifications and preferences."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="api_user@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="API User",
            contact_number="09170000003",
        )
        self.client.force_authenticate(user=self.user)

    def test_list_notifications_and_unread_count(self) -> None:
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="10"
        )
        n2 = create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_ACCEPTANCE, reference_id="11"
        )
        mark_notification_as_read(notification_id=n2.pk, user=self.user)

        res = self.client.get("/api/v1/notifications/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 2)
        self.assertEqual(res.data["unread_count"], 1)
        self.assertEqual(len(res.data["results"]), 2)
        self.assertEqual(res.data["results"][0]["type"], NOTIFICATION_TYPE_ACCEPTANCE)

    def test_filter_notifications_by_is_read(self) -> None:
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="10"
        )
        n2 = create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_ACCEPTANCE, reference_id="11"
        )
        mark_notification_as_read(notification_id=n2.pk, user=self.user)

        res_unread = self.client.get("/api/v1/notifications/?is_read=false")
        self.assertEqual(res_unread.status_code, status.HTTP_200_OK)
        self.assertEqual(res_unread.data["count"], 1)
        self.assertEqual(
            res_unread.data["results"][0]["type"], NOTIFICATION_TYPE_NEW_REQUEST
        )

        res_read = self.client.get("/api/v1/notifications/?is_read=true")
        self.assertEqual(res_read.status_code, status.HTTP_200_OK)
        self.assertEqual(res_read.data["count"], 1)
        self.assertEqual(
            res_read.data["results"][0]["type"], NOTIFICATION_TYPE_ACCEPTANCE
        )

    def test_tc_084_mark_notification_as_read(self) -> None:
        """TC-084: Mark a notification as read and verify unread count decreases."""
        n1 = create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="1"
        )
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_ACCEPTANCE, reference_id="2"
        )

        # Before marking read, unread count is 2
        res_count = self.client.get("/api/v1/notifications/unread-count/")
        self.assertEqual(res_count.data["unread_count"], 2)

        # Mark n1 as read
        res = self.client.post(f"/api/v1/notifications/{n1.pk}/read/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["notification"]["is_read"])
        self.assertEqual(res.data["unread_count"], 1)

        # Verify database state
        n1.refresh_from_db()
        self.assertTrue(n1.is_read)

    def test_mark_read_forbidden_for_other_user_notification(self) -> None:
        other_user = User.objects.create_user(
            email="other_api@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Other API",
            contact_number="09170000004",
        )
        notif = create_notification(
            user=other_user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="99"
        )

        res = self.client.post(f"/api/v1/notifications/{notif.pk}/read/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_all_notifications_as_read(self) -> None:
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_NEW_REQUEST, reference_id="1"
        )
        create_notification(
            user=self.user, event_name=NOTIFICATION_TYPE_ACCEPTANCE, reference_id="2"
        )

        res = self.client.post("/api/v1/notifications/read-all/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["marked_read"], 2)
        self.assertEqual(res.data["unread_count"], 0)

        self.assertEqual(
            Notification.objects.filter(user=self.user, is_read=False).count(), 0
        )

    def test_notification_preferences_flow(self) -> None:
        # GET default preferences
        res_get = self.client.get("/api/v1/auth/notification-preferences/")
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertTrue(res_get.data["requests"]["push"])
        self.assertFalse(res_get.data["messages"]["email"])

        # PUT updated preferences
        payload = {
            "requests": {"push": False, "email": True},
            "messages": {"push": True, "email": True},
        }
        res_put = self.client.put(
            "/api/v1/auth/notification-preferences/", payload, format="json"
        )
        self.assertEqual(res_put.status_code, status.HTTP_200_OK)
        self.assertFalse(res_put.data["requests"]["push"])
        self.assertTrue(res_put.data["messages"]["email"])
        self.assertTrue(res_put.data["security"]["push"])  # Remains True


class NotificationSignalsTests(TestCase):
    """Tests for automatic notification generation via post_save signals (CP-801)."""

    def setUp(self) -> None:
        self.user_a = User.objects.create_user(
            email="usera@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="User A",
            contact_number="09170000010",
        )
        self.user_b = User.objects.create_user(
            email="userb@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="User B",
            contact_number="09170000011",
        )

    def test_new_message_signal_notifies_recipient(self) -> None:
        conversation = Conversation.objects.create(
            user_a=self.user_a,
            user_b=self.user_b,
        )

        # Message from user A to user B
        Message.objects.create(
            conversation=conversation,
            sender=self.user_a,
            content="Hello user B!",
        )

        # User B should receive a new_message notification
        notif_b = Notification.objects.filter(
            user=self.user_b,
            type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
        ).first()
        self.assertIsNotNone(notif_b)
        self.assertEqual(notif_b.reference_id, str(conversation.pk))

        # User A should NOT receive a notification for their own message
        self.assertFalse(
            Notification.objects.filter(
                user=self.user_a,
                type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
            ).exists()
        )

    def test_new_review_signal_notifies_reviewee(self) -> None:
        active_status, _ = OrderStatus.objects.get_or_create(name=ORDER_STATUS_ACTIVE)
        category, _ = ListingCategory.objects.get_or_create(name="Tools")
        listing_status, _ = ListingStatus.objects.get_or_create(name="active")
        location, _ = PickupLocation.objects.get_or_create(name="Main Gate")

        listing = Listing.objects.create(
            lender=self.user_a,
            title="Hammer",
            description="Good hammer",
            category=category,
            pickup_location=location,
            status=listing_status,
        )
        order = Order.objects.create(
            listing=listing,
            borrower=self.user_b,
            status=active_status,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=2),
        )

        # User B (Borrower) reviews User A (Lender)
        Review.objects.create(
            order=order,
            reviewer=self.user_b,
            rating=5,
            comment="Great lender!",
        )

        # User A (Lender/reviewee) should receive new_review notification
        notif_a = Notification.objects.filter(
            user=self.user_a,
            type__name=NOTIFICATION_TYPE_NEW_REVIEW,
        ).first()
        self.assertIsNotNone(notif_a)
        self.assertEqual(notif_a.reference_id, str(order.pk))


class NotificationWorkflowIntegrationTests(TestCase):
    """End-to-end tests for key platform event notifications (CP-801, TC-083, TC-127, TC-128)."""

    def setUp(self) -> None:
        self.lender = User.objects.create_user(
            email="lender_flow@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Lender Flow",
            contact_number="09170000020",
        )
        self.borrower = User.objects.create_user(
            email="borrower_flow@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Borrower Flow",
            contact_number="09170000021",
        )
        category, _ = ListingCategory.objects.get_or_create(name="Calculators")
        status_avail, _ = ListingStatus.objects.get_or_create(name="active")
        location, _ = PickupLocation.objects.get_or_create(name="Library")

        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Scientific Calculator",
            description="Casio fx-991EX",
            category=category,
            pickup_location=location,
            status=status_avail,
        )
        AvailabilityWindow.objects.create(
            listing=self.listing,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
        )

        doc_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        doc_status, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        IdentityDocument.objects.create(
            user=self.borrower,
            document_type=doc_type,
            status=doc_status,
            id_number="2023-12345-MN-0",
            document_data=b"dummy",
            consent_given=True,
            consented_at=timezone.now(),
        )

    def test_tc_083_new_request_generates_notification(self) -> None:
        """TC-083: In-app notification generated for a new request."""
        order = request_borrow(
            borrower=self.borrower,
            listing_id=self.listing.pk,
            start_date=timezone.localdate() + timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=3),
        )

        # Lender should have a new_request notification
        notif = Notification.objects.filter(
            user=self.lender,
            type__name=NOTIFICATION_TYPE_NEW_REQUEST,
            reference_id=str(order.pk),
        ).first()
        self.assertIsNotNone(notif)
        self.assertFalse(notif.is_read)

    def test_tc_127_order_cancellation_notifies_other_party(self) -> None:
        """TC-127: Other party is notified when a Requested order is cancelled."""
        order = request_borrow(
            borrower=self.borrower,
            listing_id=self.listing.pk,
            start_date=timezone.localdate() + timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=3),
        )
        # Clear request notifications for clean check
        Notification.objects.all().delete()

        # Borrower cancels the order
        cancel_order(order_id=order.pk, actor=self.borrower, reason="Schedule conflict")

        # Lender receives cancellation notification
        notif = Notification.objects.filter(
            user=self.lender,
            type__name=NOTIFICATION_TYPE_CANCELLATION,
            reference_id=str(order.pk),
        ).first()
        self.assertIsNotNone(notif)

    def test_tc_128_overdue_sweep_notifies_both_parties(self) -> None:
        """TC-128: Both parties are notified when an order becomes Overdue."""
        active_status, _ = OrderStatus.objects.get_or_create(name=ORDER_STATUS_ACTIVE)
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=active_status,
            start_date=timezone.localdate() - timedelta(days=5),
            end_date=timezone.localdate() - timedelta(days=1),  # yesterday
        )

        summary = process_overdue_and_unreturned_orders()
        self.assertIn(order.pk, summary["overdue_order_ids"])

        # Both borrower and lender should receive overdue_status notification
        borrower_notif = Notification.objects.filter(
            user=self.borrower,
            type__name=NOTIFICATION_TYPE_OVERDUE_STATUS,
            reference_id=str(order.pk),
        ).first()
        lender_notif = Notification.objects.filter(
            user=self.lender,
            type__name=NOTIFICATION_TYPE_OVERDUE_STATUS,
            reference_id=str(order.pk),
        ).first()
        self.assertIsNotNone(borrower_notif)
        self.assertIsNotNone(lender_notif)

    def test_upcoming_due_date_sweep_notifies_borrower(self) -> None:
        """CP-801: Borrower receives notification 1 day before due date."""
        active_status, _ = OrderStatus.objects.get_or_create(name=ORDER_STATUS_ACTIVE)
        order = Order.objects.create(
            listing=self.listing,
            borrower=self.borrower,
            status=active_status,
            start_date=timezone.localdate() - timedelta(days=2),
            end_date=timezone.localdate() + timedelta(days=1),  # tomorrow
        )

        notifs = process_upcoming_due_date_notifications()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0].user_id, self.borrower.pk)
        self.assertEqual(notifs[0].type.name, NOTIFICATION_TYPE_UPCOMING_DUE_DATE)
        self.assertEqual(notifs[0].reference_id, str(order.pk))

        # Sweep again does not duplicate
        notifs2 = process_upcoming_due_date_notifications()
        self.assertEqual(len(notifs2), 0)
