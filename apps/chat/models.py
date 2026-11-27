from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ConversationQuerySet(models.QuerySet):
    """Custom queryset enforcing CP-703 retention locks on bulk deletions."""

    def delete(self):
        from .selectors import is_conversation_retained

        retained = [conv for conv in self if is_conversation_retained(conv)]
        if retained:
            raise models.ProtectedError(
                "Cannot delete conversations retained for open report or dispute review.",
                set(retained),
            )
        return super().delete()


class ConversationManager(models.Manager.from_queryset(ConversationQuerySet)):
    pass


class MessageQuerySet(models.QuerySet):
    """Custom queryset enforcing CP-703 retention locks on bulk message deletions."""

    def delete(self):
        from .selectors import is_conversation_retained

        conversations_checked: dict[int, bool] = {}
        retained_messages: list[Message] = []
        for msg in self.select_related("conversation"):
            conv_id = msg.conversation_id
            if conv_id not in conversations_checked:
                conversations_checked[conv_id] = is_conversation_retained(
                    msg.conversation
                )
            if conversations_checked[conv_id]:
                retained_messages.append(msg)
        if retained_messages:
            raise models.ProtectedError(
                "Cannot delete messages from conversations retained for open report or dispute review.",
                set(retained_messages),
            )
        return super().delete()


class MessageManager(models.Manager.from_queryset(MessageQuerySet)):
    pass


class Conversation(models.Model):
    """
    Direct 1-to-1 conversation thread between two users (FR10, CP-701/702/703).
    Optionally scoped to a specific Listing or Order.
    Blocking is prohibited while an order between the two users is in progress.
    Conversations linked to open reports or disputed orders are retained for Admin review.
    """

    conversation_id = models.BigAutoField(primary_key=True)
    user_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_user_a",
    )
    user_b = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_user_b",
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    is_blocked = models.BooleanField(default=False)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocked_conversations",
    )
    user_a_deleted_at = models.DateTimeField(null=True, blank=True)
    user_b_deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConversationManager()

    class Meta:
        db_table = "conversations"
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"
        indexes = [
            models.Index(fields=["user_a", "user_b"], name="idx_conv_users"),
            models.Index(fields=["updated_at"], name="idx_conv_updated_at"),
            models.Index(fields=["order"], name="idx_conv_order"),
        ]

    def __str__(self) -> str:
        return (
            f"Conversation #{self.conversation_id} "
            f"({self.user_a.full_name} & {self.user_b.full_name})"
        )

    def has_participant(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in (self.user_a_id, self.user_b_id)

    def other_participant(self, user):
        if user.pk == self.user_a_id:
            return self.user_b
        if user.pk == self.user_b_id:
            return self.user_a
        return None

    def is_deleted_for(self, user_id: int | None) -> bool:
        if user_id == self.user_a_id:
            return self.user_a_deleted_at is not None
        if user_id == self.user_b_id:
            return self.user_b_deleted_at is not None
        return False

    def delete(self, using=None, keep_parents=False):
        from .selectors import is_conversation_retained

        if is_conversation_retained(self):
            raise models.ProtectedError(
                "Cannot delete a conversation retained for open report or dispute review.",
                {self},
            )
        return super().delete(using=using, keep_parents=keep_parents)


class Message(models.Model):
    """Individual chat message within a conversation (FR10, CP-701)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    content = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = MessageManager()

    class Meta:
        db_table = "messages"
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        indexes = [
            models.Index(
                fields=["conversation", "sent_at"],
                name="idx_msg_conv_sent_at",
            ),
            models.Index(
                fields=["conversation", "read_at"],
                name="idx_msg_conv_read_at",
            ),
        ]

    def __str__(self) -> str:
        return f"Message #{self.id} from {self.sender.full_name}"

    def delete(self, using=None, keep_parents=False):
        from .selectors import is_conversation_retained

        if self.conversation_id and is_conversation_retained(self.conversation):
            raise models.ProtectedError(
                "Cannot delete a message from a conversation retained for open report or dispute review.",
                {self},
            )
        return super().delete(using=using, keep_parents=keep_parents)


class UserBlock(models.Model):
    """
    User-to-user chat block record (FR10, CP-702).
    Prevents new messages and new threads across all conversations between blocker and blocked.
    Creation is disallowed while an in-progress order exists between the two users.
    """

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_blocks_initiated",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_blocks_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_blocks"
        verbose_name = "User Block"
        verbose_name_plural = "User Blocks"
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"],
                name="unique_user_block",
            ),
            models.CheckConstraint(
                condition=~Q(blocker=F("blocked")),
                name="prevent_self_user_block",
            ),
        ]
        indexes = [
            models.Index(fields=["blocker", "blocked"], name="idx_user_block_pair"),
        ]

    def __str__(self) -> str:
        return f"{self.blocker.full_name} blocked {self.blocked.full_name}"
