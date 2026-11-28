"""Automated tests for FR10 Chatting: CP-701, CP-702, and CP-703."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.db.models import ProtectedError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.audit.models import AdminAccessLog
from apps.chat.admin import ConversationAdmin
from apps.chat.constants import (
    CODE_ACTIVE_ORDER_IN_PROGRESS,
    CODE_CONVERSATION_BLOCKED,
    CODE_NOT_BLOCKER,
    CODE_SELF_CHAT,
    CODE_USER_BLOCKED,
    IN_PROGRESS_ORDER_STATUSES,
)
from apps.chat.models import Conversation, Message, UserBlock
from apps.chat.selectors import (
    get_conversation_retention_info,
    is_conversation_retained,
)
from apps.listings.models import (
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.notifications.constants import NOTIFICATION_TYPE_NEW_MESSAGE
from apps.notifications.models import Notification
from apps.orders.constants import (
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_DECLINED,
    ORDER_STATUS_DISPUTED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_REQUESTED,
    ORDER_STATUS_UNRETURNED,
)
from apps.orders.models import Dispute, Order, OrderStatus
from apps.reports.models import (
    ListingReport,
    ListingReportCategory,
    MessageReport,
    MessageReportCategory,
    UserReport,
    UserReportCategory,
)
from apps.users.models import User


class ChatBaseTestCase(APITestCase):
    """Shared fixtures for CP-701, CP-702, and CP-703 chat tests."""

    def setUp(self) -> None:
        self.borrower = User.objects.create_user(
            email="borrower_chat@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Juan Borrower",
            contact_number="09171110001",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.lender = User.objects.create_user(
            email="lender_chat@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Maria Lender",
            contact_number="09171110002",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.outsider = User.objects.create_user(
            email="outsider_chat@iskolarngbayan.pup.edu.ph",
            password="StrongPassword123!",
            full_name="Pedro Outsider",
            contact_number="09171110003",
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            email_verified_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            email="admin_chat@pup.edu.ph",
            password="AdminPassword123!",
            full_name="Admin Reviewer",
            contact_number="09171110099",
        )

        self.category, _ = ListingCategory.objects.get_or_create(name="Textbooks")
        self.active_listing_status, _ = ListingStatus.objects.get_or_create(
            name="active"
        )
        self.deleted_listing_status, _ = ListingStatus.objects.get_or_create(
            name="deleted"
        )
        self.pickup_location, _ = PickupLocation.objects.get_or_create(
            name="PUP Main Library"
        )

        self.listing = Listing.objects.create(
            lender=self.lender,
            title="Calculus 1 Textbook",
            description="Slightly used textbook with notes.",
            category=self.category,
            condition="Good",
            pickup_location=self.pickup_location,
            status=self.active_listing_status,
            is_ownership_confirmed=True,
        )
        self.second_listing = Listing.objects.create(
            lender=self.lender,
            title="Scientific Calculator",
            description="Casio fx-991EX",
            category=self.category,
            condition="Like New",
            pickup_location=self.pickup_location,
            status=self.active_listing_status,
            is_ownership_confirmed=True,
        )

    def _create_order(
        self,
        *,
        status_name: str = ORDER_STATUS_CONFIRMED,
        borrower: User | None = None,
        listing: Listing | None = None,
        start_offset_days: int = 1,
        end_offset_days: int = 3,
    ) -> Order:
        order_status, _ = OrderStatus.objects.get_or_create(name=status_name)
        today = timezone.localdate()
        return Order.objects.create(
            listing=listing or self.listing,
            borrower=borrower or self.borrower,
            start_date=today + timedelta(days=start_offset_days),
            end_date=today + timedelta(days=end_offset_days),
            status=order_status,
        )


class ChatMessagingCP701Tests(ChatBaseTestCase):
    """Tests for CP-701: entry points, message storage/history, polling, and unread indicators."""

    def test_start_chat_from_listing_entry_point_is_idempotent(self) -> None:
        self.client.force_authenticate(user=self.borrower)

        res1 = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        conv_id = res1.data["conversation_id"]
        self.assertEqual(res1.data["listing"]["id"], self.listing.pk)
        self.assertEqual(res1.data["other_user"]["id"], self.lender.pk)
        self.assertEqual(res1.data["other_user"]["affiliation"], "Student")
        self.assertEqual(res1.data["participant_affiliation"], "Student")
        self.assertFalse(res1.data["has_unread"])

        # Calling again from listing or generic endpoint reuses the same conversation
        res2 = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["conversation_id"], conv_id)

        res3 = self.client.post(
            "/api/v1/conversations/",
            {"listing_id": self.listing.pk},
            format="json",
        )
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        self.assertEqual(res3.data["conversation_id"], conv_id)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_cannot_start_chat_with_self_or_on_deleted_listing(self) -> None:
        self.client.force_authenticate(user=self.lender)
        res_self = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        self.assertEqual(res_self.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_self.data["code"], CODE_SELF_CHAT)

        self.listing.status = self.deleted_listing_status
        self.listing.save(update_fields=["status"])
        self.client.force_authenticate(user=self.borrower)
        res_deleted = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        self.assertEqual(res_deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_start_chat_from_order_and_promote_existing_listing_thread(self) -> None:
        # Borrower starts a listing chat first and sends a pre-order question
        self.client.force_authenticate(user=self.borrower)
        listing_res = self.client.post(
            f"/api/v1/listings/{self.listing.pk}/chat/",
            {"initial_message": "Is this still available for Monday?"},
            format="json",
        )
        self.assertEqual(listing_res.status_code, status.HTTP_201_CREATED)
        conv_id = listing_res.data["conversation_id"]

        # Order is created; Lender opens chat from the order entry point
        order = self._create_order(status_name=ORDER_STATUS_REQUESTED)
        self.client.force_authenticate(user=self.lender)
        order_res = self.client.post(f"/api/v1/orders/{order.pk}/chat/")
        self.assertEqual(order_res.status_code, status.HTTP_200_OK)
        self.assertEqual(order_res.data["conversation_id"], conv_id)
        self.assertEqual(order_res.data["order"]["id"], order.pk)
        self.assertEqual(order_res.data["unread_count"], 1)
        self.assertTrue(order_res.data["has_unread"])

        # Outsider attempting to open chat on the order gets 404 (no ID leakage)
        self.client.force_authenticate(user=self.outsider)
        outsider_res = self.client.post(f"/api/v1/orders/{order.pk}/chat/")
        self.assertEqual(outsider_res.status_code, status.HTTP_404_NOT_FOUND)

    def test_start_fresh_chat_from_order_entry_point(self) -> None:
        order = self._create_order(status_name=ORDER_STATUS_CONFIRMED)
        self.client.force_authenticate(user=self.borrower)
        res = self.client.post(f"/api/v1/orders/{order.pk}/chat/")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["order"]["id"], order.pk)
        self.assertEqual(res.data["listing"]["id"], self.listing.pk)
        self.assertEqual(res.data["other_user"]["id"], self.lender.pk)

    def test_message_storage_history_polling_and_unread_indicator(self) -> None:
        order = self._create_order(status_name=ORDER_STATUS_CONFIRMED)
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(f"/api/v1/orders/{order.pk}/chat/")
        conv_id = conv_res.data["conversation_id"]

        # Borrower sends two messages
        m1 = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "Hi, can we meet at PUP Main Library at 2 PM?"},
            format="json",
        )
        self.assertEqual(m1.status_code, status.HTTP_201_CREATED)
        m2 = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "I will bring my PUP ID."},
            format="json",
        )
        self.assertEqual(m2.status_code, status.HTTP_201_CREATED)

        # Blank messages are rejected
        blank_res = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "   "},
            format="json",
        )
        self.assertEqual(blank_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Sender has 0 unread messages; recipient has 2 unread messages + new_message notification
        sender_counts = self.client.get("/api/v1/conversations/unread-count/")
        self.assertEqual(sender_counts.data["unread_count"], 0)

        self.client.force_authenticate(user=self.lender)
        lender_counts = self.client.get("/api/v1/conversations/unread-count/")
        self.assertEqual(lender_counts.status_code, status.HTTP_200_OK)
        self.assertEqual(lender_counts.data["unread_count"], 2)
        self.assertEqual(lender_counts.data["unread_conversations_count"], 1)

        lender_list = self.client.get("/api/v1/conversations/")
        self.assertEqual(lender_list.status_code, status.HTTP_200_OK)
        self.assertEqual(lender_list.data["total_unread_count"], 2)
        self.assertEqual(lender_list.data["results"][0]["unread_count"], 2)
        self.assertTrue(lender_list.data["results"][0]["has_unread"])

        self.assertTrue(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
                reference_id=str(conv_id),
                is_read=False,
            ).exists()
        )

        # Full history is chronological
        hist_res = self.client.get(f"/api/v1/conversations/{conv_id}/messages/")
        self.assertEqual(hist_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(hist_res.data["results"]), 2)
        self.assertEqual(hist_res.data["results"][0]["id"], m1.data["id"])
        self.assertEqual(hist_res.data["results"][1]["id"], m2.data["id"])

        # Incremental polling via ?after_id=
        poll_res = self.client.get(
            f"/api/v1/conversations/{conv_id}/messages/?after_id={m1.data['id']}"
        )
        self.assertEqual(poll_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(poll_res.data["results"]), 1)
        self.assertEqual(poll_res.data["results"][0]["id"], m2.data["id"])

        # Mark conversation read clears unread count & linked new_message notifications
        read_res = self.client.post(f"/api/v1/conversations/{conv_id}/read/")
        self.assertEqual(read_res.status_code, status.HTTP_200_OK)
        self.assertEqual(read_res.data["marked_read"], 2)
        self.assertEqual(read_res.data["unread_count"], 0)
        self.assertEqual(read_res.data["total_unread_count"], 0)

        self.assertFalse(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
                reference_id=str(conv_id),
                is_read=False,
            ).exists()
        )

        # Outsider cannot read or send messages in this private conversation
        self.client.force_authenticate(user=self.outsider)
        self.assertEqual(
            self.client.get(f"/api/v1/conversations/{conv_id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/conversations/{conv_id}/messages/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/conversations/{conv_id}/messages/",
                {"content": "sneaky"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )


class ChatBlockingCP702Tests(ChatBaseTestCase):
    """Tests for CP-702: blocking users in chat and disabling blocks while an order is in progress."""

    def test_block_allowed_with_no_in_progress_order_and_stops_new_messages(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(
            f"/api/v1/listings/{self.listing.pk}/chat/",
            {"initial_message": "Hello!"},
            format="json",
        )
        conv_id = conv_res.data["conversation_id"]
        self.assertTrue(conv_res.data["can_block"])
        self.assertIsNone(conv_res.data["block_disabled_reason"])

        # Lender blocks borrower (no order exists)
        self.client.force_authenticate(user=self.lender)
        block_res = self.client.post(f"/api/v1/conversations/{conv_id}/block/")
        self.assertEqual(block_res.status_code, status.HTTP_200_OK)
        self.assertTrue(block_res.data["is_blocked"])
        self.assertEqual(block_res.data["blocked_by_id"], self.lender.pk)
        self.assertTrue(block_res.data["is_blocked_by_me"])
        self.assertTrue(
            UserBlock.objects.filter(
                blocker=self.lender, blocked=self.borrower
            ).exists()
        )

        # Block list contains the blocked user
        blocks_list = self.client.get("/api/v1/chat/blocks/")
        self.assertEqual(blocks_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(blocks_list.data), 1)
        self.assertEqual(blocks_list.data[0]["blocked_user"]["id"], self.borrower.pk)

        # Neither party can send new messages while blocked
        send_lender = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "Wait"},
            format="json",
        )
        self.assertEqual(send_lender.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(send_lender.data["code"], CODE_CONVERSATION_BLOCKED)

        self.client.force_authenticate(user=self.borrower)
        send_borrower = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "Please reply"},
            format="json",
        )
        self.assertEqual(send_borrower.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(send_borrower.data["code"], CODE_CONVERSATION_BLOCKED)

        # Blocked user cannot start a new thread on a different listing either
        new_thread = self.client.post(
            f"/api/v1/listings/{self.second_listing.pk}/chat/"
        )
        self.assertEqual(new_thread.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(new_thread.data["code"], CODE_USER_BLOCKED)

        # Blocked user cannot unblock themselves
        bad_unblock = self.client.post(f"/api/v1/conversations/{conv_id}/unblock/")
        self.assertEqual(bad_unblock.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(bad_unblock.data["code"], CODE_NOT_BLOCKER)

        # Blocker can unblock, allowing messaging to resume
        self.client.force_authenticate(user=self.lender)
        unblock_res = self.client.post(f"/api/v1/conversations/{conv_id}/unblock/")
        self.assertEqual(unblock_res.status_code, status.HTTP_200_OK)
        self.assertFalse(unblock_res.data["is_blocked"])

        self.client.force_authenticate(user=self.borrower)
        resumed_msg = self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "Thanks for unblocking!"},
            format="json",
        )
        self.assertEqual(resumed_msg.status_code, status.HTTP_201_CREATED)

    def test_block_disabled_for_every_in_progress_order_status(self) -> None:
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        conv_id = conv_res.data["conversation_id"]

        for order_status_name in IN_PROGRESS_ORDER_STATUSES:
            with self.subTest(order_status=order_status_name):
                Order.objects.all().delete()
                # Avoid overdue/expiry sweeps mutating our target status during test setup
                start_offset = (
                    -5
                    if order_status_name
                    in (ORDER_STATUS_OVERDUE, ORDER_STATUS_UNRETURNED)
                    else 1
                )
                end_offset = (
                    -1
                    if order_status_name
                    in (ORDER_STATUS_OVERDUE, ORDER_STATUS_UNRETURNED)
                    else 4
                )
                order = self._create_order(
                    status_name=order_status_name,
                    start_offset_days=start_offset,
                    end_offset_days=end_offset,
                )

                # Both borrower and lender see can_block=False and get 409 on block attempts
                for actor, target in (
                    (self.borrower, self.lender),
                    (self.lender, self.borrower),
                ):
                    self.client.force_authenticate(user=actor)
                    detail = self.client.get(f"/api/v1/conversations/{conv_id}/")
                    self.assertFalse(detail.data["can_block"])
                    self.assertIsNotNone(detail.data["block_disabled_reason"])

                    block_conv = self.client.post(
                        f"/api/v1/conversations/{conv_id}/block/"
                    )
                    self.assertEqual(block_conv.status_code, status.HTTP_409_CONFLICT)
                    self.assertEqual(
                        block_conv.data["code"], CODE_ACTIVE_ORDER_IN_PROGRESS
                    )

                    block_user = self.client.post(f"/api/v1/users/{target.pk}/block/")
                    self.assertEqual(block_user.status_code, status.HTTP_409_CONFLICT)
                    self.assertEqual(
                        block_user.data["code"], CODE_ACTIVE_ORDER_IN_PROGRESS
                    )

                # Messaging remains open while order is in progress
                self.client.force_authenticate(user=self.borrower)
                msg = self.client.post(
                    f"/api/v1/conversations/{conv_id}/messages/",
                    {"content": f"Coordinating order #{order.pk}"},
                    format="json",
                )
                self.assertEqual(msg.status_code, status.HTTP_201_CREATED)

    def test_block_allowed_after_order_resolves(self) -> None:
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(f"/api/v1/listings/{self.listing.pk}/chat/")
        conv_id = conv_res.data["conversation_id"]

        for resolved_status in (
            ORDER_STATUS_COMPLETED,
            ORDER_STATUS_CANCELLED,
            ORDER_STATUS_DECLINED,
            ORDER_STATUS_EXPIRED,
        ):
            with self.subTest(resolved_status=resolved_status):
                Order.objects.all().delete()
                UserBlock.objects.all().delete()
                Conversation.objects.filter(conversation_id=conv_id).update(
                    is_blocked=False, blocked_by=None
                )
                self._create_order(status_name=resolved_status)

                self.client.force_authenticate(user=self.borrower)
                res = self.client.post(f"/api/v1/conversations/{conv_id}/block/")
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                self.assertTrue(res.data["is_blocked"])

    def test_block_disabled_when_roles_are_reversed_dual_role_users(self) -> None:
        # Borrower also owns a listing and Lender borrows from them
        self.borrower.lender_status = User.LenderStatusChoices.ACTIVE
        self.borrower.save(update_fields=["lender_status"])
        reverse_listing = Listing.objects.create(
            lender=self.borrower,
            title="Lab Goggles",
            description="Safety goggles",
            category=self.category,
            condition="Good",
            pickup_location=self.pickup_location,
            status=self.active_listing_status,
            is_ownership_confirmed=True,
        )
        self._create_order(
            status_name=ORDER_STATUS_ACTIVE,
            borrower=self.lender,
            listing=reverse_listing,
        )

        self.client.force_authenticate(user=self.lender)
        res = self.client.post(f"/api/v1/users/{self.borrower.pk}/block/")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data["code"], CODE_ACTIVE_ORDER_IN_PROGRESS)


class ChatRetentionCP703Tests(ChatBaseTestCase):
    """Tests for CP-703: retaining conversations linked to open reports or Disputed orders."""

    def test_unlinked_conversation_deleted_by_both_parties_is_removed(self) -> None:
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(
            f"/api/v1/listings/{self.listing.pk}/chat/",
            {"initial_message": "Quick question"},
            format="json",
        )
        conv_id = conv_res.data["conversation_id"]

        # First participant deletes -> hidden for borrower, still visible to lender
        del1 = self.client.delete(f"/api/v1/conversations/{conv_id}/")
        self.assertEqual(del1.status_code, status.HTTP_200_OK)
        self.assertFalse(del1.data["deleted"])
        self.assertFalse(del1.data["retained"])
        self.assertEqual(self.client.get("/api/v1/conversations/").data["count"], 0)

        self.client.force_authenticate(user=self.lender)
        self.assertEqual(self.client.get("/api/v1/conversations/").data["count"], 1)

        # Second participant deletes -> unlinked conversation is physically removed
        del2 = self.client.delete(f"/api/v1/conversations/{conv_id}/")
        self.assertEqual(del2.status_code, status.HTTP_200_OK)
        self.assertTrue(del2.data["deleted"])
        self.assertFalse(Conversation.objects.filter(conversation_id=conv_id).exists())

    def test_conversation_linked_to_open_message_report_is_retained_over_block_and_delete(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(
            f"/api/v1/listings/{self.listing.pk}/chat/",
            {"initial_message": "Abusive message content"},
            format="json",
        )
        conv_id = conv_res.data["conversation_id"]
        conv = Conversation.objects.get(conversation_id=conv_id)
        msg = conv.messages.first()

        # Lender files an open MessageReport
        cat, _ = MessageReportCategory.objects.get_or_create(name="harassment")
        MessageReport.objects.create(
            reporter=self.lender,
            target_message=msg,
            category=cat,
            description="Harassing message in chat.",
            status="open",
        )

        self.assertTrue(is_conversation_retained(conv))
        retention = get_conversation_retention_info(conv)
        self.assertIn("open_message_report", retention["reasons"])

        # Lender blocks borrower AND both users attempt to delete the conversation
        self.client.force_authenticate(user=self.lender)
        block_res = self.client.post(f"/api/v1/conversations/{conv_id}/block/")
        self.assertEqual(block_res.status_code, status.HTTP_200_OK)
        self.assertTrue(block_res.data["is_blocked"])
        self.assertTrue(block_res.data["is_retained"])

        del_lender = self.client.delete(f"/api/v1/conversations/{conv_id}/")
        self.assertEqual(del_lender.status_code, status.HTTP_200_OK)
        self.assertFalse(del_lender.data["deleted"])
        self.assertTrue(del_lender.data["retained"])

        self.client.force_authenticate(user=self.borrower)
        del_borrower = self.client.delete(f"/api/v1/conversations/{conv_id}/")
        self.assertEqual(del_borrower.status_code, status.HTTP_200_OK)
        self.assertFalse(del_borrower.data["deleted"])
        self.assertTrue(del_borrower.data["retained"])

        # DB rows and messages remain completely intact
        self.assertTrue(Conversation.objects.filter(conversation_id=conv_id).exists())
        self.assertEqual(Message.objects.filter(conversation_id=conv_id).count(), 1)

        # Direct ORM hard-delete is blocked by ProtectedError
        with self.assertRaises(ProtectedError):
            conv.delete()
        with self.assertRaises(ProtectedError):
            Conversation.objects.filter(conversation_id=conv_id).delete()
        with self.assertRaises(ProtectedError):
            msg.delete()
        with self.assertRaises(ProtectedError):
            Message.objects.filter(conversation_id=conv_id).delete()

        # Non-admin user cannot access Admin review endpoints
        self.assertEqual(
            self.client.get("/api/v1/admin/conversations/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/admin/conversations/{conv_id}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Admin can list and inspect the retained conversation + messages despite block & delete
        self.client.force_authenticate(user=self.admin)
        admin_list = self.client.get("/api/v1/admin/conversations/?retained=true")
        self.assertEqual(admin_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(admin_list.data), 1)
        self.assertEqual(admin_list.data[0]["conversation_id"], conv_id)
        self.assertTrue(admin_list.data[0]["is_retained"])
        self.assertTrue(admin_list.data[0]["is_blocked"])

        admin_detail = self.client.get(f"/api/v1/admin/conversations/{conv_id}/")
        self.assertEqual(admin_detail.status_code, status.HTTP_200_OK)
        self.assertTrue(admin_detail.data["is_retained"])
        self.assertIn("open_message_report", admin_detail.data["retention_reasons"])
        self.assertEqual(len(admin_detail.data["messages"]), 1)
        self.assertEqual(
            admin_detail.data["messages"][0]["content"], "Abusive message content"
        )
        self.assertIsNotNone(admin_detail.data["user_a_deleted_at"])
        self.assertIsNotNone(admin_detail.data["user_b_deleted_at"])

        # Admin access is recorded in immutable AdminAccessLog
        self.assertTrue(
            AdminAccessLog.objects.filter(
                admin=self.admin,
                action="view_conversation",
                target_type="conversation",
                target_id=str(conv_id),
            ).exists()
        )

        # CoPUPAdmin Portal reports & review queues link to and render the retained chat viewer
        self.client.force_login(self.admin)
        reports_page = self.client.get(
            reverse("portal-reports-queue") + "?type=message"
        )
        self.assertEqual(reports_page.status_code, status.HTTP_200_OK)
        chat_portal_url = reverse("portal-conversation-detail", args=[conv_id])
        self.assertContains(reports_page, chat_portal_url)

        review_queues_page = self.client.get(
            reverse("portal-review-queues") + "?tab=reports"
        )
        self.assertEqual(review_queues_page.status_code, status.HTTP_200_OK)
        self.assertContains(review_queues_page, chat_portal_url)
        self.assertContains(review_queues_page, "View Chat")

        portal_chat = self.client.get(chat_portal_url)
        self.assertEqual(portal_chat.status_code, status.HTTP_200_OK)
        self.assertContains(portal_chat, "Abusive message content")
        self.assertContains(portal_chat, "Retained for Review")

    def test_conversation_linked_to_disputed_order_is_retained_and_embedded_in_dispute_dossier(
        self,
    ) -> None:
        order = self._create_order(status_name=ORDER_STATUS_DISPUTED)
        dispute = Dispute.objects.create(
            order=order,
            raised_by=self.lender,
            description="Pages torn on return.",
            status=Dispute.StatusChoices.OPEN,
        )

        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(
            f"/api/v1/orders/{order.pk}/chat/",
            {"initial_message": "The book already had a loose cover at handover."},
            format="json",
        )
        conv_id = conv_res.data["conversation_id"]
        self.assertTrue(conv_res.data["is_retained"])

        # Lender blocks and both users attempt to delete the conversation
        self.client.force_authenticate(user=self.lender)
        self.assertEqual(
            self.client.post(f"/api/v1/conversations/{conv_id}/block/").status_code,
            status.HTTP_200_OK,
        )
        self.assertTrue(
            self.client.delete(f"/api/v1/conversations/{conv_id}/").data["retained"]
        )
        self.client.force_authenticate(user=self.borrower)
        self.assertTrue(
            self.client.delete(f"/api/v1/conversations/{conv_id}/").data["retained"]
        )

        # Admin Dispute dossier embeds the retained conversation & messages
        self.client.force_authenticate(user=self.admin)
        dossier_res = self.client.get(f"/api/v1/disputes/{dispute.pk}/")
        self.assertEqual(dossier_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(dossier_res.data["chat"]), 1)
        self.assertEqual(dossier_res.data["chat"][0]["conversation_id"], conv_id)
        self.assertTrue(dossier_res.data["chat"][0]["is_retained"])
        self.assertTrue(dossier_res.data["chat"][0]["is_blocked"])
        self.assertEqual(
            dossier_res.data["chat"][0]["messages"][0]["content"],
            "The book already had a loose cover at handover.",
        )

    def test_open_user_report_and_listing_report_retain_conversation(self) -> None:
        conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.lender,
            listing=self.listing,
        )
        self.assertFalse(is_conversation_retained(conv))

        user_cat, _ = UserReportCategory.objects.get_or_create(name="scam_fraud")
        user_report = UserReport.objects.create(
            reporter=self.borrower,
            target_user=self.lender,
            category=user_cat,
            description="Suspicious off-platform demands.",
            status="open",
        )
        self.assertTrue(is_conversation_retained(conv))
        self.assertIn(
            "open_user_report", get_conversation_retention_info(conv)["reasons"]
        )

        # Resolving the user report releases retention if no other report/dispute exists
        user_report.status = "resolved"
        user_report.save(update_fields=["status"])
        self.assertFalse(is_conversation_retained(conv))

        listing_cat, _ = ListingReportCategory.objects.get_or_create(
            name="misleading_description"
        )
        ListingReport.objects.create(
            reporter=self.borrower,
            target_listing=self.listing,
            category=listing_cat,
            description="Item condition misrepresented.",
            status="open",
        )
        self.assertTrue(is_conversation_retained(conv))
        self.assertIn(
            "open_listing_report", get_conversation_retention_info(conv)["reasons"]
        )

    def test_django_admin_delete_permission_blocked_for_retained_conversation(
        self,
    ) -> None:
        order = self._create_order(status_name=ORDER_STATUS_DISPUTED)
        conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.lender,
            listing=self.listing,
            order=order,
        )
        unlinked_conv = Conversation.objects.create(
            user_a=self.borrower,
            user_b=self.outsider,
        )

        model_admin = ConversationAdmin(Conversation, AdminSite())
        req = RequestFactory().get("/admin/chat/conversation/")
        req.user = self.admin

        self.assertFalse(model_admin.has_delete_permission(req, obj=conv))
        self.assertTrue(model_admin.has_delete_permission(req, obj=unlinked_conv))


class ClientAlignmentContractTests(ChatBaseTestCase):
    """Verify Kimodri's CP-701/702/703 routes and payload shapes match brb-client expectations."""

    def test_chats_alias_participant_start_text_message_and_user_block_routes(
        self,
    ) -> None:
        self.client.force_authenticate(user=self.borrower)

        # Start thread directly with participant_id via /api/v1/chats/
        start_res = self.client.post(
            "/api/v1/chats/",
            {"participant_id": self.lender.pk, "initial_message": "Hey there!"},
            format="json",
        )
        self.assertEqual(start_res.status_code, status.HTTP_201_CREATED)
        conv_id = start_res.data["id"]
        self.assertEqual(start_res.data["participant_id"], self.lender.pk)
        self.assertEqual(start_res.data["participant_name"], self.lender.full_name)
        self.assertFalse(start_res.data["blocked_by_me"])
        self.assertEqual(start_res.data["last_message"]["text"], "Hey there!")

        # Post message with {text} payload and read via /api/v1/chats/<id>/messages/
        send_res = self.client.post(
            f"/api/v1/chats/{conv_id}/messages/",
            {"text": "Can I ask about pickup?"},
            format="json",
        )
        self.assertEqual(send_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(send_res.data["text"], "Can I ask about pickup?")
        self.assertEqual(send_res.data["content"], "Can I ask about pickup?")
        self.assertTrue(send_res.data["is_mine"])
        self.assertIn("created_at", send_res.data)

        list_res = self.client.get("/api/v1/chats/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            list_res.data["results"][0]["last_message"]["text"],
            "Can I ask about pickup?",
        )

        # Mark read alias works for recipient
        self.client.force_authenticate(user=self.lender)
        read_res = self.client.post(f"/api/v1/chats/{conv_id}/read/")
        self.assertEqual(read_res.status_code, status.HTTP_200_OK)
        self.assertEqual(read_res.data["marked_read"], 2)

        # Block status GET + unblock POST routes
        status_before = self.client.get(f"/api/v1/users/{self.borrower.pk}/block/")
        self.assertEqual(status_before.status_code, status.HTTP_200_OK)
        self.assertFalse(status_before.data["is_blocked"])
        self.assertFalse(status_before.data["blocked_by_me"])

        block_res = self.client.post(f"/api/v1/users/{self.borrower.pk}/block/")
        self.assertEqual(block_res.status_code, status.HTTP_200_OK)

        status_lender = self.client.get(f"/api/v1/users/{self.borrower.pk}/block/")
        self.assertTrue(status_lender.data["is_blocked"])
        self.assertTrue(status_lender.data["blocked_by_me"])

        self.client.force_authenticate(user=self.borrower)
        status_borrower = self.client.get(f"/api/v1/users/{self.lender.pk}/block/")
        self.assertTrue(status_borrower.data["is_blocked"])
        self.assertFalse(status_borrower.data["blocked_by_me"])

        # Blocked counterparty cannot POST unblock
        self.assertEqual(
            self.client.post(f"/api/v1/users/{self.lender.pk}/unblock/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Original blocker unblocks via POST /users/<id>/unblock/
        self.client.force_authenticate(user=self.lender)
        unblock_res = self.client.post(f"/api/v1/users/{self.borrower.pk}/unblock/")
        self.assertEqual(unblock_res.status_code, status.HTTP_200_OK)
        self.assertFalse(unblock_res.data["is_blocked"])
        self.assertFalse(unblock_res.data["blocked_by_me"])

    def test_dispute_conversation_endpoint_returns_client_timeline_and_logs_access(
        self,
    ) -> None:
        order = self._create_order(status_name=ORDER_STATUS_DISPUTED)
        dispute = Dispute.objects.create(
            order=order,
            raised_by=self.lender,
            description="Scratches found at return.",
            status=Dispute.StatusChoices.OPEN,
        )

        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(
            f"/api/v1/orders/{order.pk}/chat/",
            {"initial_message": "Handing it back at Main Gate."},
            format="json",
        )
        conv_id = conv_res.data["conversation_id"]

        self.client.force_authenticate(user=self.lender)
        self.client.post(
            f"/api/v1/conversations/{conv_id}/messages/",
            {"content": "Received, checking condition now."},
            format="json",
        )

        # Non-staff blocked
        self.client.force_authenticate(user=self.borrower)
        self.assertEqual(
            self.client.get(f"/api/v1/disputes/{dispute.pk}/conversation/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Admin gets [{id, sender: borrower|lender, text, sentAt}] and audit log
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f"/api/v1/disputes/{dispute.pk}/conversation/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)
        self.assertEqual(res.data[0]["sender"], "borrower")
        self.assertEqual(res.data[0]["text"], "Handing it back at Main Gate.")
        self.assertIn("sentAt", res.data[0])
        self.assertEqual(res.data[1]["sender"], "lender")
        self.assertEqual(res.data[1]["text"], "Received, checking condition now.")
        self.assertTrue(
            AdminAccessLog.objects.filter(
                admin=self.admin,
                action="view_conversation",
                target_type="dispute",
                target_id=str(dispute.pk),
            ).exists()
        )

    def test_replying_clears_unread_count_and_updates_last_message_in_list(
        self,
    ) -> None:
        order = self._create_order(status_name=ORDER_STATUS_CONFIRMED)
        self.client.force_authenticate(user=self.borrower)
        conv_res = self.client.post(f"/api/v1/orders/{order.pk}/chat/")
        conv_id = conv_res.data["conversation_id"]

        self.client.post(
            f"/api/v1/chats/{conv_id}/messages/",
            {"text": "Hello from Neo"},
            format="json",
        )

        # Lender has 1 unread message before replying.
        self.client.force_authenticate(user=self.lender)
        before_list = self.client.get("/api/v1/chats/")
        self.assertEqual(before_list.status_code, status.HTTP_200_OK)
        self.assertEqual(before_list.data["results"][0]["unread_count"], 1)
        self.assertEqual(
            before_list.data["results"][0]["last_message"]["text"], "Hello from Neo"
        )
        self.assertFalse(before_list.data["results"][0]["last_message"]["is_mine"])

        # Lender replies directly without separately hitting /read/.
        reply_res = self.client.post(
            f"/api/v1/chats/{conv_id}/messages/",
            {"text": "Yes, still available!"},
            format="json",
        )
        self.assertEqual(reply_res.status_code, status.HTTP_201_CREATED)

        after_list = self.client.get("/api/v1/chats/")
        self.assertEqual(after_list.status_code, status.HTTP_200_OK)
        self.assertEqual(after_list.data["results"][0]["unread_count"], 0)
        self.assertFalse(after_list.data["results"][0]["has_unread"])
        self.assertEqual(
            after_list.data["results"][0]["last_message"]["text"],
            "Yes, still available!",
        )
        self.assertTrue(after_list.data["results"][0]["last_message"]["is_mine"])
        self.assertFalse(
            Notification.objects.filter(
                user=self.lender,
                type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
                reference_id=str(conv_id),
                is_read=False,
            ).exists()
        )
