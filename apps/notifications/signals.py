"""Signal handlers for dispatching event notifications (CP-801, FR11)."""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.chat.models import Message
from apps.reviews.models import Review

from .constants import NOTIFICATION_TYPE_NEW_MESSAGE, NOTIFICATION_TYPE_NEW_REVIEW
from .services import create_notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def handle_new_message_notification(
    sender, instance: Message, created: bool, **kwargs
) -> None:
    """Notify the conversation counterparty when a new message is sent."""
    if not created:
        return

    try:
        conversation = instance.conversation
        recipient = (
            conversation.user_b
            if instance.sender_id == conversation.user_a_id
            else conversation.user_a
        )
        if recipient:
            create_notification(
                user=recipient,
                event_name=NOTIFICATION_TYPE_NEW_MESSAGE,
                reference_id=conversation.pk,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CP-801: failed to dispatch message notification for Message #%d: %s",
            instance.pk,
            exc,
        )


@receiver(post_save, sender=Review)
def handle_new_review_notification(
    sender, instance: Review, created: bool, **kwargs
) -> None:
    """Notify the reviewed party when a mutual review is submitted."""
    if not created:
        return

    try:
        reviewee = instance.reviewee
        if reviewee:
            create_notification(
                user=reviewee,
                event_name=NOTIFICATION_TYPE_NEW_REVIEW,
                reference_id=instance.order_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CP-801: failed to dispatch review notification for Review #%d: %s",
            instance.pk,
            exc,
        )
