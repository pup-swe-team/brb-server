"""Read-only selectors and retention/unread queries for the chat domain (CP-701, CP-702, CP-703)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Count, F, Max, Q, QuerySet
from django.db.models.functions import Coalesce

from apps.orders.constants import (
    ORDER_STATUS_DISPUTED,
    UNRETURNED_CASE_STATUS_ESCALATED,
    UNRETURNED_CASE_STATUS_OPEN,
)
from apps.orders.models import Dispute, Order, UnreturnedCase
from apps.reports.constants import REPORT_STATUS_OPEN
from apps.reports.models import ListingReport, MessageReport, UserReport
from apps.users.models import User

from .constants import IN_PROGRESS_ORDER_STATUSES
from .models import Conversation, Message, UserBlock


def pair_conversation_q(user_1_id: int, user_2_id: int) -> Q:
    """Match conversations between two users regardless of user_a/user_b column order."""
    return Q(user_a_id=user_1_id, user_b_id=user_2_id) | Q(
        user_a_id=user_2_id, user_b_id=user_1_id
    )


def pair_order_q(user_1_id: int, user_2_id: int) -> Q:
    """Match orders between two users in either borrower/lender direction."""
    return Q(borrower_id=user_1_id, listing__lender_id=user_2_id) | Q(
        borrower_id=user_2_id, listing__lender_id=user_1_id
    )


def get_in_progress_orders_between_users(
    user_1_id: int,
    user_2_id: int,
) -> QuerySet[Order]:
    """Return orders between two users that are still in progress (CP-702)."""
    return (
        Order.objects.filter(
            pair_order_q(user_1_id, user_2_id),
            status__name__in=IN_PROGRESS_ORDER_STATUSES,
        )
        .select_related("status", "listing")
        .order_by("-created_at", "-pk")
    )


def has_in_progress_order_between_users(user_1_id: int, user_2_id: int) -> bool:
    """Whether an in-progress order currently prevents blocking between two users (CP-702)."""
    return get_in_progress_orders_between_users(user_1_id, user_2_id).exists()


def get_active_blocks_between_users(
    user_1_id: int,
    user_2_id: int,
) -> QuerySet[UserBlock]:
    """Return active UserBlock records in either direction between two users."""
    return UserBlock.objects.filter(
        Q(blocker_id=user_1_id, blocked_id=user_2_id)
        | Q(blocker_id=user_2_id, blocked_id=user_1_id)
    ).select_related("blocker", "blocked")


def get_active_block_between_users(
    user_1_id: int,
    user_2_id: int,
) -> UserBlock | None:
    """Return any active UserBlock record between two users, if one exists."""
    return get_active_blocks_between_users(user_1_id, user_2_id).first()


def is_conversation_blocked(conversation: Conversation) -> bool:
    """
    Effective block state for a conversation: True if either the conversation row
    is marked blocked or an active UserBlock exists between its participants.
    """
    if conversation.is_blocked:
        return True
    return get_active_blocks_between_users(
        conversation.user_a_id, conversation.user_b_id
    ).exists()


def get_conversation_retention_info(conversation: Conversation) -> dict[str, Any]:
    """
    Evaluate CP-703 retention status for a conversation.

    A conversation is retained for Admin review if it is linked to any:
      - open MessageReport on one of its messages
      - open UserReport between its participants (matching the conversation's order or general)
      - open ListingReport filed by either participant on the conversation's listing
      - Disputed order or open/escalated Dispute linked to the conversation
      - open/escalated UnreturnedCase linked to the conversation's order/listing
    """
    user_a_id = conversation.user_a_id
    user_b_id = conversation.user_b_id

    open_message_report_ids = list(
        MessageReport.objects.filter(
            target_message__conversation_id=conversation.conversation_id,
            status=REPORT_STATUS_OPEN,
        ).values_list("pk", flat=True)
    )

    user_reports_qs = UserReport.objects.filter(
        Q(reporter_id=user_a_id, target_user_id=user_b_id)
        | Q(reporter_id=user_b_id, target_user_id=user_a_id),
        status=REPORT_STATUS_OPEN,
    )
    if conversation.order_id is not None:
        user_reports_qs = user_reports_qs.filter(
            Q(order_id=conversation.order_id) | Q(order__isnull=True)
        )
    open_user_report_ids = list(user_reports_qs.values_list("pk", flat=True))

    open_listing_report_ids: list[int] = []
    if conversation.listing_id is not None:
        open_listing_report_ids = list(
            ListingReport.objects.filter(
                target_listing_id=conversation.listing_id,
                reporter_id__in=(user_a_id, user_b_id),
                status=REPORT_STATUS_OPEN,
            ).values_list("pk", flat=True)
        )

    if conversation.order_id is not None:
        relevant_orders = Order.objects.filter(pk=conversation.order_id)
    elif conversation.listing_id is not None:
        relevant_orders = Order.objects.filter(
            pair_order_q(user_a_id, user_b_id),
            listing_id=conversation.listing_id,
        )
    else:
        relevant_orders = Order.objects.filter(pair_order_q(user_a_id, user_b_id))

    open_dispute_qs = Dispute.objects.filter(
        order__in=relevant_orders,
        status__in=(Dispute.StatusChoices.OPEN, Dispute.StatusChoices.ESCALATED),
    )
    open_dispute_ids = list(open_dispute_qs.values_list("pk", flat=True))

    disputed_order_ids = list(
        relevant_orders.filter(
            Q(status__name=ORDER_STATUS_DISPUTED) | Q(disputes__in=open_dispute_qs)
        )
        .distinct()
        .values_list("pk", flat=True)
    )

    open_unreturned_case_ids = list(
        UnreturnedCase.objects.filter(
            order__in=relevant_orders,
            status__name__in=(
                UNRETURNED_CASE_STATUS_OPEN,
                UNRETURNED_CASE_STATUS_ESCALATED,
            ),
        ).values_list("pk", flat=True)
    )

    reasons: list[str] = []
    if open_message_report_ids:
        reasons.append("open_message_report")
    if open_user_report_ids:
        reasons.append("open_user_report")
    if open_listing_report_ids:
        reasons.append("open_listing_report")
    if disputed_order_ids or open_dispute_ids:
        reasons.append("disputed_order")
    if open_unreturned_case_ids:
        reasons.append("open_unreturned_case")

    return {
        "is_retained": bool(reasons),
        "reasons": reasons,
        "open_report_ids": {
            "message": open_message_report_ids,
            "user": open_user_report_ids,
            "listing": open_listing_report_ids,
        },
        "disputed_order_ids": disputed_order_ids,
        "open_dispute_ids": open_dispute_ids,
        "open_unreturned_case_ids": open_unreturned_case_ids,
    }


def is_conversation_retained(conversation: Conversation) -> bool:
    """Boolean shortcut for CP-703 conversation retention checks."""
    return get_conversation_retention_info(conversation)["is_retained"]


def visible_conversations_for_user(user: User) -> QuerySet[Conversation]:
    """Return conversations where `user` is a participant and has not hidden/deleted them."""
    return Conversation.objects.filter(
        Q(user_a=user, user_a_deleted_at__isnull=True)
        | Q(user_b=user, user_b_deleted_at__isnull=True)
    )


def list_user_conversations(user: User) -> QuerySet[Conversation]:
    """
    List visible conversations for `user` annotated with unread counts and latest activity.
    """
    return (
        visible_conversations_for_user(user)
        .select_related(
            "user_a",
            "user_b",
            "listing",
            "listing__pickup_location",
            "order",
            "order__status",
            "blocked_by",
        )
        .prefetch_related("listing__photos")
        .annotate(
            unread_count=Count(
                "messages",
                filter=Q(messages__read_at__isnull=True)
                & ~Q(messages__sender_id=user.pk),
            ),
            latest_message_at=Max("messages__sent_at"),
            sort_timestamp=Coalesce(Max("messages__sent_at"), F("updated_at")),
        )
        .order_by("-sort_timestamp", "-conversation_id")
    )


def get_user_unread_chat_counts(user: User) -> dict[str, int]:
    """Return total unread messages and count of conversations with unread messages."""
    visible_ids = visible_conversations_for_user(user).values_list(
        "conversation_id", flat=True
    )
    unread_qs = Message.objects.filter(
        conversation_id__in=visible_ids,
        read_at__isnull=True,
    ).exclude(sender=user)
    return {
        "unread_count": unread_qs.count(),
        "unread_conversations_count": unread_qs.values("conversation_id")
        .distinct()
        .count(),
    }


def get_conversation_messages(
    conversation: Conversation,
    *,
    after_id: int | None = None,
    since: datetime | None = None,
) -> QuerySet[Message]:
    """
    Return chronological messages for a conversation, supporting short-interval polling
    via `after_id` or `since` (SRS §5.3, CP-701).
    """
    qs = (
        Message.objects.filter(conversation=conversation)
        .select_related("sender")
        .order_by("sent_at", "id")
    )
    if after_id is not None:
        qs = qs.filter(id__gt=after_id)
    if since is not None:
        qs = qs.filter(sent_at__gt=since)
    return qs


def get_conversations_for_order_dossier(order: Order) -> list[dict[str, Any]]:
    """
    Serialize all conversations (including blocked or user-deleted threads) linked to
    an order or between the order's parties for the same listing (CP-703, CP-506, FR8).
    """
    borrower = order.borrower
    lender = order.listing.lender
    conversations = (
        Conversation.objects.filter(
            Q(order=order)
            | (Q(listing=order.listing) & pair_conversation_q(borrower.pk, lender.pk))
        )
        .select_related("user_a", "user_b", "blocked_by")
        .prefetch_related("messages__sender")
        .order_by("created_at", "conversation_id")
        .distinct()
    )
    result: list[dict[str, Any]] = []
    for conv in conversations:
        retention = get_conversation_retention_info(conv)
        result.append(
            {
                "conversation_id": conv.conversation_id,
                "order_id": conv.order_id,
                "listing_id": conv.listing_id,
                "is_blocked": is_conversation_blocked(conv),
                "blocked_by_id": conv.blocked_by_id,
                "is_retained": retention["is_retained"],
                "retention_reasons": retention["reasons"],
                "user_a_deleted_at": (
                    conv.user_a_deleted_at.isoformat()
                    if conv.user_a_deleted_at
                    else None
                ),
                "user_b_deleted_at": (
                    conv.user_b_deleted_at.isoformat()
                    if conv.user_b_deleted_at
                    else None
                ),
                "messages": [
                    {
                        "id": msg.pk,
                        "sender_id": msg.sender_id,
                        "sender_name": msg.sender.full_name,
                        "content": msg.content,
                        "sent_at": msg.sent_at.isoformat(),
                        "read_at": msg.read_at.isoformat() if msg.read_at else None,
                    }
                    for msg in conv.messages.all().order_by("sent_at", "pk")
                ],
            }
        )
    return result


def list_admin_conversations(
    *,
    retained: bool | None = None,
    order_id: int | None = None,
    listing_id: int | None = None,
    user_id: int | None = None,
    is_blocked: bool | None = None,
) -> list[Conversation]:
    """
    Return conversations for Admin review regardless of block or user-delete status (CP-703).
    """
    qs = (
        Conversation.objects.select_related(
            "user_a",
            "user_b",
            "listing",
            "order",
            "order__status",
            "blocked_by",
        )
        .annotate(message_count=Count("messages"))
        .order_by("-updated_at", "-conversation_id")
    )

    if order_id is not None:
        qs = qs.filter(order_id=order_id)
    if listing_id is not None:
        qs = qs.filter(listing_id=listing_id)
    if user_id is not None:
        qs = qs.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id))
    if is_blocked is not None:
        qs = qs.filter(is_blocked=is_blocked)

    conversations = list(qs)
    if retained is not None:
        conversations = [
            conv for conv in conversations if is_conversation_retained(conv) == retained
        ]
    return conversations
