"""Business logic services for 1-to-1 chat, user blocking, and retention (CP-701, CP-702, CP-703)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.listings.constants import LISTING_STATUS_DELETED
from apps.listings.models import Listing
from apps.notifications.constants import NOTIFICATION_TYPE_NEW_MESSAGE
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.users.models import User

from .constants import (
    CODE_ACCOUNT_INACTIVE,
    CODE_ACTIVE_ORDER_IN_PROGRESS,
    CODE_CONVERSATION_BLOCKED,
    CODE_INVALID_CHAT_TARGET,
    CODE_NOT_BLOCKER,
    CODE_SELF_BLOCK,
    CODE_SELF_CHAT,
    CODE_USER_BLOCKED,
    MAX_MESSAGE_LENGTH,
)
from .models import Conversation, Message, UserBlock
from .selectors import (
    get_active_block_between_users,
    get_conversation_retention_info,
    get_in_progress_orders_between_users,
    is_conversation_blocked,
    pair_conversation_q,
)


class ChatConflictError(APIException):
    """409 Conflict for chat state guards (e.g., blocking while an order is in progress)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action cannot be completed right now."
    default_code = CODE_ACTIVE_ORDER_IN_PROGRESS


def _ensure_active_account(user: User) -> None:
    if user.account_status in (
        User.AccountStatusChoices.SUSPENDED,
        User.AccountStatusChoices.BANNED,
        User.AccountStatusChoices.DEACTIVATED,
    ):
        raise PermissionDenied(
            "Your account is not active and cannot perform chat actions.",
            code=CODE_ACCOUNT_INACTIVE,
        )


def _canonical_pair(user_1: User, user_2: User) -> tuple[User, User]:
    """Order two participants deterministically by primary key."""
    return (user_1, user_2) if user_1.pk < user_2.pk else (user_2, user_1)


def _unhide_for_user(conversation: Conversation, user_id: int) -> None:
    if user_id == conversation.user_a_id and conversation.user_a_deleted_at is not None:
        conversation.user_a_deleted_at = None
        conversation.save(update_fields=["user_a_deleted_at", "updated_at"])
    elif (
        user_id == conversation.user_b_id and conversation.user_b_deleted_at is not None
    ):
        conversation.user_b_deleted_at = None
        conversation.save(update_fields=["user_b_deleted_at", "updated_at"])


def get_participant_conversation(*, conversation_id: int, user: User) -> Conversation:
    """
    Fetch a conversation ensuring `user` is one of its participants.
    Returns 404 for outsiders to avoid leaking private thread IDs (CONTRIBUTING.md §5.3.9).
    """
    conversation = get_object_or_404(
        Conversation.objects.select_related(
            "user_a",
            "user_b",
            "listing",
            "listing__pickup_location",
            "order",
            "order__status",
            "blocked_by",
        ),
        conversation_id=conversation_id,
    )
    if not conversation.has_participant(user.pk):
        raise Http404("Conversation not found.")
    return conversation


@transaction.atomic
def start_or_get_conversation(
    *,
    requester: User,
    participant_id: int | None = None,
    listing_id: int | None = None,
    order_id: int | None = None,
    initial_message: str | None = None,
) -> tuple[Conversation, bool]:
    """
    Start or retrieve an existing 1-to-1 conversation from an order, listing, or
    direct participant ID (CP-701).

    Returns `(conversation, created)`.
    """
    _ensure_active_account(requester)

    if listing_id is None and order_id is None and participant_id is None:
        raise ValidationError(
            {
                "detail": (
                    "Either participant_id, listing_id, or order_id is required to start a chat."
                )
            },
            code=CODE_INVALID_CHAT_TARGET,
        )

    created = False
    conv_rels = (
        "user_a",
        "user_b",
        "listing",
        "order",
        "order__status",
        "blocked_by",
    )

    if order_id is not None:
        order = get_object_or_404(
            Order.objects.select_related(
                "listing",
                "listing__lender",
                "listing__pickup_location",
                "borrower",
                "status",
            ),
            pk=order_id,
        )
        if requester.pk not in (order.borrower_id, order.listing.lender_id):
            raise Http404("Order not found.")
        if listing_id is not None and listing_id != order.listing_id:
            raise ValidationError(
                {"listing_id": "listing_id does not match the specified order."},
                code=CODE_INVALID_CHAT_TARGET,
            )

        counterparty = (
            order.listing.lender
            if requester.pk == order.borrower_id
            else order.borrower
        )
        if participant_id is not None and participant_id != counterparty.pk:
            raise ValidationError(
                {"participant_id": "participant_id does not match the order party."},
                code=CODE_INVALID_CHAT_TARGET,
            )
        if counterparty.pk == requester.pk:
            raise ValidationError(
                {"detail": "You cannot start a conversation with yourself."},
                code=CODE_SELF_CHAT,
            )

        conversation = (
            Conversation.objects.select_related(*conv_rels)
            .filter(
                pair_conversation_q(requester.pk, counterparty.pk),
                order=order,
            )
            .first()
        )
        if conversation is None:
            # Promote an existing orderless listing thread between the same pair so
            # pre-order messages stay linked to the order and remain retained if disputed.
            existing_listing_conv = (
                Conversation.objects.select_related(*conv_rels)
                .filter(
                    pair_conversation_q(requester.pk, counterparty.pk),
                    listing=order.listing,
                    order__isnull=True,
                )
                .order_by("-updated_at", "-conversation_id")
                .first()
            )
            if existing_listing_conv is not None:
                existing_listing_conv.order = order
                existing_listing_conv.save(update_fields=["order", "updated_at"])
                conversation = existing_listing_conv
            else:
                active_block = get_active_block_between_users(
                    requester.pk, counterparty.pk
                )
                user_a, user_b = _canonical_pair(requester, counterparty)
                conversation = Conversation.objects.create(
                    user_a=user_a,
                    user_b=user_b,
                    listing=order.listing,
                    order=order,
                    is_blocked=active_block is not None,
                    blocked_by=active_block.blocker if active_block else None,
                )
                created = True
        _unhide_for_user(conversation, requester.pk)
    elif listing_id is not None:
        listing = get_object_or_404(
            Listing.objects.select_related("lender", "status", "pickup_location"),
            pk=listing_id,
        )
        if listing.status.name == LISTING_STATUS_DELETED or (
            listing.status.name == "deactivated" and listing.lender_id != requester.pk
        ):
            raise Http404("Listing not found.")

        if requester.pk == listing.lender_id:
            if participant_id is None or participant_id == requester.pk:
                raise ValidationError(
                    {"detail": "You cannot start a conversation with yourself."},
                    code=CODE_SELF_CHAT,
                )
            counterparty = get_object_or_404(User, pk=participant_id)
        else:
            counterparty = listing.lender
            if participant_id is not None and participant_id != counterparty.pk:
                raise ValidationError(
                    {
                        "participant_id": (
                            "participant_id does not match the listing owner."
                        )
                    },
                    code=CODE_INVALID_CHAT_TARGET,
                )

        conversation = (
            Conversation.objects.select_related(*conv_rels)
            .filter(
                pair_conversation_q(requester.pk, counterparty.pk),
                listing=listing,
                order__isnull=True,
            )
            .order_by("-updated_at", "-conversation_id")
            .first()
        )
        if conversation is None:
            conversation = (
                Conversation.objects.select_related(*conv_rels)
                .filter(
                    pair_conversation_q(requester.pk, counterparty.pk),
                    listing=listing,
                )
                .order_by("-updated_at", "-conversation_id")
                .first()
            )

        if conversation is None:
            if get_active_block_between_users(requester.pk, counterparty.pk):
                raise PermissionDenied(
                    "You cannot start a new conversation with this user because messaging is blocked.",
                    code=CODE_USER_BLOCKED,
                )
            user_a, user_b = _canonical_pair(requester, counterparty)
            conversation = Conversation.objects.create(
                user_a=user_a,
                user_b=user_b,
                listing=listing,
            )
            created = True
        else:
            _unhide_for_user(conversation, requester.pk)
    else:
        counterparty = get_object_or_404(User, pk=participant_id)
        if counterparty.pk == requester.pk:
            raise ValidationError(
                {"detail": "You cannot start a conversation with yourself."},
                code=CODE_SELF_CHAT,
            )

        conversation = (
            Conversation.objects.select_related(*conv_rels)
            .filter(
                pair_conversation_q(requester.pk, counterparty.pk),
                listing__isnull=True,
                order__isnull=True,
            )
            .order_by("-updated_at", "-conversation_id")
            .first()
        )
        if conversation is None:
            conversation = (
                Conversation.objects.select_related(*conv_rels)
                .filter(pair_conversation_q(requester.pk, counterparty.pk))
                .order_by("-updated_at", "-conversation_id")
                .first()
            )

        if conversation is None:
            if get_active_block_between_users(requester.pk, counterparty.pk):
                raise PermissionDenied(
                    "You cannot start a new conversation with this user because messaging is blocked.",
                    code=CODE_USER_BLOCKED,
                )
            user_a, user_b = _canonical_pair(requester, counterparty)
            conversation = Conversation.objects.create(
                user_a=user_a,
                user_b=user_b,
            )
            created = True
        else:
            _unhide_for_user(conversation, requester.pk)

    if initial_message is not None and initial_message.strip():
        send_message(
            conversation=conversation,
            sender=requester,
            content=initial_message,
        )

    return conversation, created


@transaction.atomic
def send_message(
    *,
    conversation: Conversation,
    sender: User,
    content: str,
) -> Message:
    """
    Persist a message in a conversation (CP-701), enforcing block guards (CP-702).
    The post_save signal in `apps/notifications/signals.py` automatically notifies the recipient.
    """
    _ensure_active_account(sender)
    if not conversation.has_participant(sender.pk):
        raise Http404("Conversation not found.")

    cleaned = (content or "").strip()
    if not cleaned:
        raise ValidationError(
            {"content": "Message content cannot be blank."},
            code="blank_message",
        )
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise ValidationError(
            {"content": f"Message cannot exceed {MAX_MESSAGE_LENGTH} characters."},
            code="message_too_long",
        )

    if is_conversation_blocked(conversation):
        raise PermissionDenied(
            "This conversation is blocked and cannot receive new messages.",
            code=CODE_CONVERSATION_BLOCKED,
        )

    message = Message.objects.create(
        conversation=conversation,
        sender=sender,
        content=cleaned,
    )

    update_fields = ["updated_at"]
    if conversation.user_a_deleted_at is not None:
        conversation.user_a_deleted_at = None
        update_fields.append("user_a_deleted_at")
    if conversation.user_b_deleted_at is not None:
        conversation.user_b_deleted_at = None
        update_fields.append("user_b_deleted_at")
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=update_fields)

    return message


@transaction.atomic
def mark_conversation_read(
    *,
    conversation: Conversation,
    reader: User,
) -> int:
    """
    Mark all unread incoming messages in `conversation` as read for `reader` (CP-701),
    and mark matching `new_message` in-app notifications as read.
    """
    if not conversation.has_participant(reader.pk):
        raise Http404("Conversation not found.")

    now = timezone.now()
    updated = (
        Message.objects.filter(
            conversation=conversation,
            read_at__isnull=True,
        )
        .exclude(sender=reader)
        .update(read_at=now)
    )

    Notification.objects.filter(
        user=reader,
        type__name=NOTIFICATION_TYPE_NEW_MESSAGE,
        reference_id=str(conversation.conversation_id),
        is_read=False,
    ).update(is_read=True)

    return updated


@transaction.atomic
def block_user_from_chat(
    *,
    blocker: User,
    target_user: User,
) -> UserBlock:
    """
    Block another user in chat (CP-702).

    Disabled (409 Conflict) while any order between the two users in either role is
    still in progress (Requested, Confirmed, Active, Overdue, Unreturned).
    """
    _ensure_active_account(blocker)
    if blocker.pk == target_user.pk:
        raise ValidationError(
            {"detail": "You cannot block yourself."},
            code=CODE_SELF_BLOCK,
        )

    from apps.orders.services import (
        expire_unanswered_requests,
        process_overdue_and_unreturned_orders,
    )

    expire_unanswered_requests()
    process_overdue_and_unreturned_orders()

    blocking_order = get_in_progress_orders_between_users(
        blocker.pk, target_user.pk
    ).first()
    if blocking_order is not None:
        raise ChatConflictError(
            detail=(
                "Blocking is disabled while an order between you and this user is "
                f"still in progress (Order #{blocking_order.pk}: {blocking_order.status.name})."
            ),
            code=CODE_ACTIVE_ORDER_IN_PROGRESS,
        )

    block, _ = UserBlock.objects.get_or_create(
        blocker=blocker,
        blocked=target_user,
    )

    Conversation.objects.filter(pair_conversation_q(blocker.pk, target_user.pk)).update(
        is_blocked=True,
        blocked_by=blocker,
        updated_at=timezone.now(),
    )

    return block


@transaction.atomic
def unblock_user_from_chat(
    *,
    requester: User,
    target_user: User,
) -> None:
    """
    Unblock a user previously blocked by `requester` (CP-702).
    Only the user who initiated the block can lift it.
    """
    _ensure_active_account(requester)
    if requester.pk == target_user.pk:
        raise ValidationError(
            {"detail": "You cannot unblock yourself."},
            code=CODE_SELF_BLOCK,
        )

    own_block = UserBlock.objects.filter(
        blocker=requester,
        blocked=target_user,
    ).first()
    reverse_block = UserBlock.objects.filter(
        blocker=target_user,
        blocked=requester,
    ).first()

    if own_block is None:
        if reverse_block is not None:
            raise PermissionDenied(
                "Only the user who initiated the block can unblock this conversation.",
                code=CODE_NOT_BLOCKER,
            )
        # Handle legacy/direct conversation.is_blocked state without a UserBlock row
        legacy_blocked_by_other = (
            Conversation.objects.filter(
                pair_conversation_q(requester.pk, target_user.pk),
                is_blocked=True,
            )
            .exclude(blocked_by=requester)
            .exclude(blocked_by__isnull=True)
            .exists()
        )
        if legacy_blocked_by_other:
            raise PermissionDenied(
                "Only the user who initiated the block can unblock this conversation.",
                code=CODE_NOT_BLOCKER,
            )
    else:
        own_block.delete()

    convs = Conversation.objects.filter(
        pair_conversation_q(requester.pk, target_user.pk)
    )
    if reverse_block is not None:
        convs.update(
            is_blocked=True,
            blocked_by=target_user,
            updated_at=timezone.now(),
        )
    else:
        convs.update(
            is_blocked=False,
            blocked_by=None,
            updated_at=timezone.now(),
        )


@transaction.atomic
def delete_conversation_for_user(
    *,
    conversation: Conversation,
    user: User,
) -> dict[str, Any]:
    """
    Remove/hide a conversation from `user`'s inbox with CP-703 retention override.

    - If the conversation is linked to an open report, Disputed order, or open
      UnreturnedCase, the DB record and all messages are preserved intact for Admin
      review even if both participants delete or block it.
    - If not retained, stamps the caller's deleted_at; when both participants have
      deleted an unretained conversation, physically deletes the thread.
    """
    if not conversation.has_participant(user.pk):
        raise Http404("Conversation not found.")

    now = timezone.now()
    if user.pk == conversation.user_a_id:
        conversation.user_a_deleted_at = now
        deleted_field = "user_a_deleted_at"
    else:
        conversation.user_b_deleted_at = now
        deleted_field = "user_b_deleted_at"

    retention = get_conversation_retention_info(conversation)
    conversation.save(update_fields=[deleted_field, "updated_at"])

    if retention["is_retained"]:
        return {
            "deleted": False,
            "hidden": True,
            "retained": True,
            "retention_reasons": retention["reasons"],
            "detail": (
                "Conversation hidden from your inbox and retained for administrative review."
            ),
        }

    if (
        conversation.user_a_deleted_at is not None
        and conversation.user_b_deleted_at is not None
    ):
        conversation.delete()
        return {
            "deleted": True,
            "hidden": True,
            "retained": False,
            "retention_reasons": [],
            "detail": "Conversation deleted.",
        }

    return {
        "deleted": False,
        "hidden": True,
        "retained": False,
        "retention_reasons": [],
        "detail": "Conversation removed from your inbox.",
    }
