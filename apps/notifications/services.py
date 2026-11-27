"""Services for in-app and email event notifications (FR11, CP-801, CP-802)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.orders.constants import ORDER_STATUS_ACTIVE
from apps.orders.models import Order

from .constants import (
    DEFAULT_EMAIL_NOTIFICATION_PREFERENCES,
    EVENT_TO_CATEGORY_MAP,
    NOTIFICATION_METADATA,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
    ORDER_PREFIXED_NOTIFICATION_TYPES,
    PREF_CATEGORY_ACCOUNT_VERIFICATION,
    PREF_CATEGORY_ORDER_UPDATES,
)
from .models import Notification, NotificationPreference, NotificationType

logger = logging.getLogger(__name__)
User = get_user_model()

# Backward-compatible export aliases.
DEFAULT_NOTIFICATION_PREFERENCES = DEFAULT_EMAIL_NOTIFICATION_PREFERENCES


def get_notification_type(name: str) -> NotificationType:
    """Retrieve or create the NotificationType lookup row."""
    obj, _ = NotificationType.objects.get_or_create(name=name)
    return obj


def _extract_category_enabled(raw_val: Any, default: bool = True) -> bool:
    """Interpret either a plain boolean or a legacy {'email': bool} channel dict."""
    if isinstance(raw_val, bool):
        return raw_val
    if (
        isinstance(raw_val, dict)
        and "email" in raw_val
        and isinstance(raw_val["email"], bool)
    ):
        return raw_val["email"]
    return default


def _normalize_stored_preferences(raw_prefs: Any) -> dict[str, bool]:
    """
    Normalize stored JSON preferences to CP-802's four boolean categories.
    All four categories default to True unless explicitly opted out.
    """
    result: dict[str, bool] = dict(DEFAULT_EMAIL_NOTIFICATION_PREFERENCES)
    if not isinstance(raw_prefs, dict):
        return result

    # Graceful fallback for any legacy Sprint 4 6-category rows if canonical key is absent.
    if PREF_CATEGORY_ORDER_UPDATES not in raw_prefs:
        legacy_order_vals = [
            _extract_category_enabled(raw_prefs[k], True)
            for k in ("requests", "handover", "overdue")
            if k in raw_prefs
        ]
        if legacy_order_vals:
            result[PREF_CATEGORY_ORDER_UPDATES] = any(legacy_order_vals)

    if PREF_CATEGORY_ACCOUNT_VERIFICATION not in raw_prefs and "security" in raw_prefs:
        result[PREF_CATEGORY_ACCOUNT_VERIFICATION] = _extract_category_enabled(
            raw_prefs["security"], True
        )

    for category_key in DEFAULT_EMAIL_NOTIFICATION_PREFERENCES:
        if category_key in raw_prefs:
            result[category_key] = _extract_category_enabled(
                raw_prefs[category_key], True
            )

    return result


def get_user_notification_preferences(user: User) -> dict[str, bool]:
    """
    Return the user's email notification preferences across CP-802's four categories:
    order_updates, messages, reviews, and account_verification (all True by default).
    """
    pref, _ = NotificationPreference.objects.get_or_create(
        user=user,
        defaults={"preferences": dict(DEFAULT_EMAIL_NOTIFICATION_PREFERENCES)},
    )
    return _normalize_stored_preferences(pref.preferences)


def update_user_notification_preferences(
    user: User, new_prefs: dict[str, Any]
) -> dict[str, bool]:
    """
    Update and persist email notification preferences for `user` (CP-802).
    Users may opt out of or re-enable any of the four categories individually.
    """
    current = get_user_notification_preferences(user)
    if isinstance(new_prefs, dict):
        for cat, val in new_prefs.items():
            if cat in current:
                current[cat] = _extract_category_enabled(val, current[cat])

    pref, _ = NotificationPreference.objects.get_or_create(
        user=user,
        defaults={"preferences": current},
    )
    pref.preferences = current
    pref.save(update_fields=["preferences", "updated_at"])
    return current


def get_category_for_event(event_name: str) -> str | None:
    """Map a NotificationType event name to its CP-802 preference category."""
    return EVENT_TO_CATEGORY_MAP.get(event_name)


def should_send_email_for_event(*, user: User, event_name: str) -> bool:
    """
    Determine whether an email notification should be sent to `user` for `event_name` (CP-802).
    Returns True only when the user has an email address and has not opted out of the event's category.
    """
    if user is None or not getattr(user, "email", None):
        return False

    category = get_category_for_event(event_name)
    if category is None:
        return False

    prefs = get_user_notification_preferences(user)
    return bool(prefs.get(category, True))


def build_notification_email(*, notification: Notification) -> tuple[str, str]:
    """Build plain-text subject and body for an event notification email (CP-802)."""
    event_name = notification.type.name
    meta = NOTIFICATION_METADATA.get(event_name, {})
    title = meta.get("title", event_name.replace("_", " ").title())
    base_msg = meta.get("message", "You have a new notification on BRB.")
    if notification.reference_id and event_name in ORDER_PREFIXED_NOTIFICATION_TYPES:
        detail_line = f"Order #{notification.reference_id}: {base_msg}"
    else:
        detail_line = base_msg

    recipient_name = notification.user.full_name or "there"
    subject = f"BRB — {title}"
    body = (
        f"Hi {recipient_name},\n\n"
        f"{detail_line}\n\n"
        "Open the BRB app to view full details. "
        "You can manage your email notification preferences anytime in your account settings.\n\n"
        "Thank you,\n"
        "BRB Team\n"
    )
    return subject, body


def send_notification_email(notification: Notification) -> bool:
    """
    Send an email notification for `notification` if the recipient has not opted out
    of its CP-802 category. Failures are logged and never raise into callers.
    """
    user = notification.user
    event_name = notification.type.name

    if not should_send_email_for_event(user=user, event_name=event_name):
        logger.info(
            "CP-802: email notification suppressed for user #%d on event '%s' (opted out)",
            user.pk,
            event_name,
        )
        return False

    subject, body = build_notification_email(notification=notification)
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=None,  # falls back to settings.DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info(
            "CP-802: sent email notification '%s' (Notification #%d) to user #%d",
            event_name,
            notification.pk,
            user.pk,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CP-802: failed to send email notification '%s' (Notification #%d) to user #%d: %s",
            event_name,
            notification.pk,
            user.pk,
            exc,
        )
        return False


def create_notification(
    *,
    user: User,
    event_name: str,
    reference_id: str | int | None = None,
) -> Notification:
    """
    Dispatch an in-app notification to `user` for event `event_name` (CP-801, FR11).

    In-app notifications are always created regardless of email preferences (CP-802).
    Email delivery is automatically gated and dispatched via the Notification post_save signal.
    Idempotent for unread notifications with the same (user, event_name, reference_id).
    """
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
