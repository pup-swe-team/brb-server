"""Serializers for 1-to-1 chat, blocking, and Admin retention review (CP-701, CP-702, CP-703)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.users.models import User

from .constants import MAX_MESSAGE_LENGTH
from .models import Conversation, Message, UserBlock
from .selectors import (
    get_active_blocks_between_users,
    get_conversation_retention_info,
    get_in_progress_orders_between_users,
    is_conversation_blocked,
)


def _build_media_url(request: Any, file_field: Any) -> str | None:
    if not file_field:
        return None
    url = file_field.url
    if request and not url.startswith("http"):
        return request.build_absolute_uri(url)
    return url


class ChatParticipantSerializer(serializers.ModelSerializer):
    """Public-safe participant summary displayed in chat threads (SRS FR1, FR10)."""

    photo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "affiliation", "photo"]
        read_only_fields = fields

    def get_photo(self, obj: User) -> str | None:
        return _build_media_url(self.context.get("request"), obj.photo)


class MessageSerializer(serializers.ModelSerializer):
    """Serialized individual chat message (CP-701)."""

    conversation_id = serializers.IntegerField(read_only=True)
    sender_id = serializers.IntegerField(read_only=True)
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)
    sender_affiliation = serializers.CharField(
        source="sender.affiliation", read_only=True
    )
    is_read = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation_id",
            "sender_id",
            "sender_name",
            "sender_affiliation",
            "content",
            "sent_at",
            "read_at",
            "is_read",
            "is_mine",
        ]
        read_only_fields = fields

    def get_is_read(self, obj: Message) -> bool:
        return obj.read_at is not None

    def get_is_mine(self, obj: Message) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and obj.sender_id == user.pk)


class StartConversationSerializer(serializers.Serializer):
    """Input payload for POST /api/v1/conversations/ (CP-701)."""

    listing_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    order_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    initial_message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=MAX_MESSAGE_LENGTH,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("listing_id") and not attrs.get("order_id"):
            raise serializers.ValidationError(
                {"detail": "Either listing_id or order_id must be provided."}
            )
        return attrs


class EntryPointChatSerializer(serializers.Serializer):
    """Optional input payload for listing/order chat start entry points (CP-701)."""

    initial_message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=MAX_MESSAGE_LENGTH,
    )


class SendMessageSerializer(serializers.Serializer):
    """Input payload for POST /api/v1/conversations/<id>/messages/ (CP-701)."""

    content = serializers.CharField(
        trim_whitespace=True,
        allow_blank=False,
        max_length=MAX_MESSAGE_LENGTH,
    )


class ConversationSerializer(serializers.ModelSerializer):
    """
    Participant-scoped conversation representation including unread indicators (CP-701),
    block controls/eligibility (CP-702), and retention flag (CP-703).
    """

    id = serializers.IntegerField(source="conversation_id", read_only=True)
    other_user = serializers.SerializerMethodField()
    listing = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    has_unread = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()
    blocked_by_id = serializers.SerializerMethodField()
    is_blocked_by_me = serializers.SerializerMethodField()
    can_block = serializers.SerializerMethodField()
    block_disabled_reason = serializers.SerializerMethodField()
    is_retained = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_id",
            "other_user",
            "listing",
            "order",
            "last_message",
            "unread_count",
            "has_unread",
            "is_blocked",
            "blocked_by_id",
            "is_blocked_by_me",
            "can_block",
            "block_disabled_reason",
            "is_retained",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _request_user(self) -> User | None:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return user if (user and user.is_authenticated) else None

    def _block_state(self, obj: Conversation) -> dict[str, Any]:
        if not hasattr(obj, "_cached_block_state"):
            user = self._request_user()
            blocks = list(get_active_blocks_between_users(obj.user_a_id, obj.user_b_id))
            blocked = obj.is_blocked or bool(blocks)
            blocked_by_id = obj.blocked_by_id
            is_blocked_by_me = False
            if user is not None:
                if any(b.blocker_id == user.pk for b in blocks):
                    is_blocked_by_me = True
                    blocked_by_id = user.pk
                elif blocks:
                    blocked_by_id = blocks[0].blocker_id
                elif blocked_by_id == user.pk:
                    is_blocked_by_me = True
            elif blocks and blocked_by_id is None:
                blocked_by_id = blocks[0].blocker_id

            in_progress = get_in_progress_orders_between_users(
                obj.user_a_id, obj.user_b_id
            ).first()
            can_block = in_progress is None
            block_disabled_reason = (
                f"Blocking is disabled while Order #{in_progress.pk} "
                f"({in_progress.status.name}) is still in progress."
                if in_progress is not None
                else None
            )
            obj._cached_block_state = {
                "is_blocked": blocked,
                "blocked_by_id": blocked_by_id,
                "is_blocked_by_me": is_blocked_by_me,
                "can_block": can_block,
                "block_disabled_reason": block_disabled_reason,
            }
        return obj._cached_block_state

    def _retention_info(self, obj: Conversation) -> dict[str, Any]:
        if not hasattr(obj, "_cached_retention_info"):
            obj._cached_retention_info = get_conversation_retention_info(obj)
        return obj._cached_retention_info

    def get_other_user(self, obj: Conversation) -> dict[str, Any] | None:
        user = self._request_user()
        other = obj.other_participant(user) if user else obj.user_b
        if other is None:
            return None
        return ChatParticipantSerializer(other, context=self.context).data

    def get_listing(self, obj: Conversation) -> dict[str, Any] | None:
        if not obj.listing_id or obj.listing is None:
            return None
        first_photo = obj.listing.photos.first()
        photo_url = (
            _build_media_url(self.context.get("request"), first_photo.file_reference)
            if first_photo
            else None
        )
        return {
            "id": obj.listing_id,
            "title": obj.listing.title,
            "photo": photo_url,
        }

    def get_order(self, obj: Conversation) -> dict[str, Any] | None:
        if not obj.order_id or obj.order is None:
            return None
        return {
            "id": obj.order_id,
            "status": obj.order.status.name if obj.order.status_id else "",
            "start_date": str(obj.order.start_date),
            "end_date": str(obj.order.end_date),
        }

    def get_last_message(self, obj: Conversation) -> dict[str, Any] | None:
        msg = obj.messages.select_related("sender").order_by("-sent_at", "-id").first()
        if msg is None:
            return None
        return MessageSerializer(msg, context=self.context).data

    def get_unread_count(self, obj: Conversation) -> int:
        if hasattr(obj, "unread_count") and obj.unread_count is not None:
            return int(obj.unread_count)
        user = self._request_user()
        if user is None:
            return 0
        return (
            obj.messages.filter(read_at__isnull=True).exclude(sender_id=user.pk).count()
        )

    def get_has_unread(self, obj: Conversation) -> bool:
        return self.get_unread_count(obj) > 0

    def get_is_blocked(self, obj: Conversation) -> bool:
        return self._block_state(obj)["is_blocked"]

    def get_blocked_by_id(self, obj: Conversation) -> int | None:
        return self._block_state(obj)["blocked_by_id"]

    def get_is_blocked_by_me(self, obj: Conversation) -> bool:
        return self._block_state(obj)["is_blocked_by_me"]

    def get_can_block(self, obj: Conversation) -> bool:
        return self._block_state(obj)["can_block"]

    def get_block_disabled_reason(self, obj: Conversation) -> str | None:
        return self._block_state(obj)["block_disabled_reason"]

    def get_is_retained(self, obj: Conversation) -> bool:
        return self._retention_info(obj)["is_retained"]


class UserBlockSerializer(serializers.ModelSerializer):
    """Serialized user block entry for the blocker's block list (CP-702)."""

    blocked_user = ChatParticipantSerializer(source="blocked", read_only=True)

    class Meta:
        model = UserBlock
        fields = ["id", "blocked_user", "created_at"]
        read_only_fields = fields


class AdminConversationListSerializer(serializers.ModelSerializer):
    """Admin summary view of any conversation including blocked/deleted retained threads (CP-703)."""

    id = serializers.IntegerField(source="conversation_id", read_only=True)
    user_a = ChatParticipantSerializer(read_only=True)
    user_b = ChatParticipantSerializer(read_only=True)
    listing_id = serializers.IntegerField(read_only=True)
    listing_title = serializers.SerializerMethodField()
    order_id = serializers.IntegerField(read_only=True)
    order_status = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()
    blocked_by_id = serializers.IntegerField(read_only=True)
    is_retained = serializers.SerializerMethodField()
    retention_reasons = serializers.SerializerMethodField()
    open_report_ids = serializers.SerializerMethodField()
    disputed_order_ids = serializers.SerializerMethodField()
    open_dispute_ids = serializers.SerializerMethodField()
    open_unreturned_case_ids = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_id",
            "user_a",
            "user_b",
            "listing_id",
            "listing_title",
            "order_id",
            "order_status",
            "is_blocked",
            "blocked_by_id",
            "user_a_deleted_at",
            "user_b_deleted_at",
            "is_retained",
            "retention_reasons",
            "open_report_ids",
            "disputed_order_ids",
            "open_dispute_ids",
            "open_unreturned_case_ids",
            "message_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _retention(self, obj: Conversation) -> dict[str, Any]:
        if not hasattr(obj, "_cached_retention_info"):
            obj._cached_retention_info = get_conversation_retention_info(obj)
        return obj._cached_retention_info

    def get_listing_title(self, obj: Conversation) -> str | None:
        return obj.listing.title if obj.listing_id and obj.listing else None

    def get_order_status(self, obj: Conversation) -> str | None:
        return (
            obj.order.status.name
            if obj.order_id and obj.order and obj.order.status_id
            else None
        )

    def get_is_blocked(self, obj: Conversation) -> bool:
        return is_conversation_blocked(obj)

    def get_is_retained(self, obj: Conversation) -> bool:
        return self._retention(obj)["is_retained"]

    def get_retention_reasons(self, obj: Conversation) -> list[str]:
        return self._retention(obj)["reasons"]

    def get_open_report_ids(self, obj: Conversation) -> dict[str, list[int]]:
        return self._retention(obj)["open_report_ids"]

    def get_disputed_order_ids(self, obj: Conversation) -> list[int]:
        return self._retention(obj)["disputed_order_ids"]

    def get_open_dispute_ids(self, obj: Conversation) -> list[int]:
        return self._retention(obj)["open_dispute_ids"]

    def get_open_unreturned_case_ids(self, obj: Conversation) -> list[int]:
        return self._retention(obj)["open_unreturned_case_ids"]

    def get_message_count(self, obj: Conversation) -> int:
        if hasattr(obj, "message_count") and obj.message_count is not None:
            return int(obj.message_count)
        return obj.messages.count()


class AdminConversationDetailSerializer(AdminConversationListSerializer):
    """Full Admin review payload with complete chronological message history (CP-703)."""

    messages = serializers.SerializerMethodField()

    class Meta(AdminConversationListSerializer.Meta):
        fields = [
            *AdminConversationListSerializer.Meta.fields,
            "messages",
        ]
        read_only_fields = fields

    def get_messages(self, obj: Conversation) -> list[dict[str, Any]]:
        qs = obj.messages.select_related("sender").order_by("sent_at", "id")
        return MessageSerializer(qs, many=True, context=self.context).data
