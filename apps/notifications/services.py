"""Services for in-app and email event notifications (FR11, CP-801, CP-802)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.orders.constants import ORDER_STATUS_ACTIVE
from apps.orders.models import Order

from .constants import (
    NOTIFICATION_TYPE_ACCEPTANCE,
    NOTIFICATION_TYPE_CANCELLATION,
    NOTIFICATION_TYPE_CODE_GENERATION,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
    NOTIFICATION_TYPE_CONFIRMED_RETURN,
    NOTIFICATION_TYPE_DECLINE,
    NOTIFICATION_TYPE_EXPIRY,
    NOTIFICATION_TYPE_NEW_MESSAGE,
    NOTIFICATION_TYPE_NEW_REQUEST,
    NOTIFICATION_TYPE_NEW_REVIEW,
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_REPORT_UPDATES,
    NOTIFICATION_TYPE_UNRETURNED_STATUS,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
    NOTIFICATION_TYPE_VERIFICATION_RESULT,
)
from .models import Notification, NotificationPreference, NotificationType

logger = logging.getLogger(__name__)
User = get_user_model()

DEFAULT_NOTIFICATION_PREFERENCES = {
    "requests": {"push": True, "email": True},
    "handover": {"push": True, "email": True},
    "overdue": {"push": True, "email": True},
    "messages": {"push": True, "email": False},
    "reviews": {"push": True, "email": True},
    "security": {"push": True, "email": True},
}

EVENT_TO_CATEGORY_MAP: dict[str, str] = {
    NOTIFICATION_TYPE_NEW_REQUEST: "requests",
    NOTIFICATION_TYPE_ACCEPTANCE: "requests",
    NOTIFICATION_TYPE_DECLINE: "requests",
    NOTIFICATION_TYPE_EXPIRY: "requests",
    NOTIFICATION_TYPE_CANCELLATION: "requests",
    NOTIFICATION_TYPE_CODE_GENERATION: "handover",
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER: "handover",
    NOTIFICATION_TYPE_CONFIRMED_RETURN: "handover",
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE: "handover",
    NOTIFICATION_TYPE_OVERDUE_STATUS: "overdue",
    NOTIFICATION_TYPE_UNRETURNED_STATUS: "overdue",
    NOTIFICATION_TYPE_NEW_MESSAGE: "messages",
    NOTIFICATION_TYPE_NEW_REVIEW: "reviews",
    NOTIFICATION_TYPE_VERIFICATION_RESULT: "security",
    NOTIFICATION_TYPE_REPORT_UPDATES: "security",
}


def get_notification_type(name: str) -> NotificationType:
    """Retrieve or create the NotificationType lookup row."""
    obj, _ = NotificationType.objects.get_or_create(name=name)
    return obj


def get_user_notification_preferences(user: User) -> dict:
    """Return the merged notification preferences dictionary for a user."""
    pref, _ = NotificationPreference.objects.get_or_create(
        user=user,
        defaults={"preferences": DEFAULT_NOTIFICATION_PREFERENCES},
    )
    result: dict[str, dict[str, bool]] = {
        cat: dict(vals) for cat, vals in DEFAULT_NOTIFICATION_PREFERENCES.items()
    }
    if isinstance(pref.preferences, dict):
        for cat, vals in pref.preferences.items():
            if cat in result and isinstance(vals, dict):
                result[cat] = {
                    "push": bool(vals.get("push", result[cat]["push"])),
                    "email": bool(vals.get("email", result[cat]["email"])),
                }
    # Security category is locked to enabled
    result["security"] = {"push": True, "email": True}
    return result


def update_user_notification_preferences(user: User, new_prefs: dict) -> dict:
    """Update and persist user notification preferences."""
    current = get_user_notification_preferences(user)
    if isinstance(new_prefs, dict):
        for cat, vals in new_prefs.items():
            if cat in current and cat != "security" and isinstance(vals, dict):
                if "push" in vals:
                    current[cat]["push"] = bool(vals["push"])
                if "email" in vals:
                    current[cat]["email"] = bool(vals["email"])

    current["security"] = {"push": True, "email": True}
    pref, _ = NotificationPreference.objects.get_or_create(
        user=user,
        defaults={"preferences": current},
    )
    pref.preferences = current
    pref.save(update_fields=["preferences", "updated_at"])
    return current


def create_notification(
    *,
    user: User,
    event_name: str,
    reference_id: str | int | None = None,
) -> Notification | None:
    """
    Dispatch an in-app notification to `user` for event `event_name` (CP-801, FR11).

    Idempotent for key events with the same reference_id to avoid duplicate spamming.
    Respects user preferences if an opt-out is configured.
    """
    category = EVENT_TO_CATEGORY_MAP.get(event_name)
    if category and category != "security":
        prefs = get_user_notification_preferences(user)
        if not prefs.get(category, {}).get("push", True):
            logger.info(
                "CP-801: in-app notification '%s' suppressed for user #%d by category preference '%s'",
                event_name,
                user.pk,
                category,
            )
            return None

    ref_str = str(reference_id) if reference_id is not None else None
    notif_type = get_notification_type(event_name)

    # Prevent duplicate unread notifications for the same event and reference
    if ref_str:
        existing = Notification.objects.filter(
            user=user,
            type=notif_type,
            reference_id=ref_str,
            is_read=False,
        ).first()
        if existing:
            return existing

    notification = Notification.objects.create(
        user=user,
        type=notif_type,
        reference_id=ref_str,
    )
    logger.info(
        "CP-801: dispatched notification '%s' (ID #%d) to user #%d (reference_id=%s)",
        event_name,
        notification.pk,
        user.pk,
        ref_str,
    )
    return notification


@transaction.atomic
def mark_notification_as_read(*, notification_id: int, user: User) -> Notification:
    """Mark a single notification as read."""
    notif = Notification.objects.select_for_update().get(pk=notification_id, user=user)
    if not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=["is_read"])
    return notif


@transaction.atomic
def mark_all_notifications_as_read(*, user: User) -> int:
    """Mark all unread notifications for `user` as read."""
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)


def process_upcoming_due_date_notifications(
    *, now: datetime | None = None
) -> list[Notification]:
    """
    Scheduled sweep or on-access check for CP-801:
    Sends `upcoming_due_date` notification to Borrowers whose active order end_date is tomorrow.
    """
    now = now or timezone.now()
    today = timezone.localdate(now)
    tomorrow = today + timedelta(days=1)

    active_orders = (
        Order.objects.filter(
            status__name=ORDER_STATUS_ACTIVE,
            end_date=tomorrow,
        )
        .select_related("borrower", "listing")
        .order_by("pk")
    )

    created_notifs: list[Notification] = []
    notif_type = get_notification_type(NOTIFICATION_TYPE_UPCOMING_DUE_DATE)

    for order in active_orders:
        ref_str = str(order.pk)
        # Only notify once per order for upcoming due date
        already_notified = Notification.objects.filter(
            user_id=order.borrower_id,
            type=notif_type,
            reference_id=ref_str,
        ).exists()

        if not already_notified:
            notif = create_notification(
                user=order.borrower,
                event_name=NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
                reference_id=ref_str,
            )
            if notif:
                created_notifs.append(notif)
            logger.info(
                "CP-801: upcoming due date reminder sent for Order #%d to Borrower #%d",
                order.pk,
                order.borrower_id,
            )

    return created_notifs
