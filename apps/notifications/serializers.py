"""Serializers for the notifications domain (FR11, CP-801, CP-802)."""

from __future__ import annotations

from rest_framework import serializers

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
from .models import Notification

NOTIFICATION_METADATA: dict[str, dict[str, str]] = {
    NOTIFICATION_TYPE_NEW_REQUEST: {
        "title": "New Borrow Request",
        "message": "You received a new borrow request.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_ACCEPTANCE: {
        "title": "Borrow Request Accepted",
        "message": "Your borrow request has been accepted by the lender.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_DECLINE: {
        "title": "Borrow Request Declined",
        "message": "Your borrow request was declined.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_EXPIRY: {
        "title": "Borrow Request Expired",
        "message": "A borrow request has expired without a lender response.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CANCELLATION: {
        "title": "Order Cancelled",
        "message": "An order has been cancelled.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CODE_GENERATION: {
        "title": "Handover Code Generated",
        "message": "A verification code has been generated for handover/return.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER: {
        "title": "Handover Confirmed",
        "message": "The item handover has been confirmed. The order is now active.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CONFIRMED_RETURN: {
        "title": "Return Confirmed",
        "message": "The item return has been confirmed. The order is completed.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE: {
        "title": "Upcoming Due Date",
        "message": "Your borrowed item is due tomorrow. Please prepare for return.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_OVERDUE_STATUS: {
        "title": "Order Overdue",
        "message": "The return deadline for your borrowed item has passed.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_UNRETURNED_STATUS: {
        "title": "Order Marked Unreturned",
        "message": "This order is significantly overdue and has been escalated as unreturned.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_NEW_MESSAGE: {
        "title": "New Message",
        "message": "You received a new message.",
        "reference_type": "conversation",
    },
    NOTIFICATION_TYPE_NEW_REVIEW: {
        "title": "New Review",
        "message": "You received a new review and rating.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_VERIFICATION_RESULT: {
        "title": "Identity Verification Update",
        "message": "Your identity verification submission has been reviewed.",
        "reference_type": "verification",
    },
    NOTIFICATION_TYPE_REPORT_UPDATES: {
        "title": "Report / Case Update",
        "message": "There is an update on your reported issue or order escalation.",
        "reference_type": "report",
    },
}


class NotificationSerializer(serializers.ModelSerializer):
    """Serialize an in-app notification with localized title and informative message."""

    type = serializers.CharField(source="type.name", read_only=True)
    title = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    reference_type = serializers.SerializerMethodField()
    order_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "message",
            "reference_id",
            "reference_type",
            "order_id",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields

    def get_title(self, obj: Notification) -> str:
        meta = NOTIFICATION_METADATA.get(obj.type.name, {})
        return meta.get("title", obj.type.name.replace("_", " ").title())

    def get_message(self, obj: Notification) -> str:
        meta = NOTIFICATION_METADATA.get(obj.type.name, {})
        base_msg = meta.get("message", "You have a new notification.")
        if obj.reference_id and obj.type.name in (
            NOTIFICATION_TYPE_NEW_REQUEST,
            NOTIFICATION_TYPE_ACCEPTANCE,
            NOTIFICATION_TYPE_DECLINE,
            NOTIFICATION_TYPE_CANCELLATION,
            NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
            NOTIFICATION_TYPE_OVERDUE_STATUS,
            NOTIFICATION_TYPE_UNRETURNED_STATUS,
            NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
            NOTIFICATION_TYPE_CONFIRMED_RETURN,
        ):
            return f"Order #{obj.reference_id}: {base_msg}"
        return base_msg

    def get_reference_type(self, obj: Notification) -> str:
        meta = NOTIFICATION_METADATA.get(obj.type.name, {})
        return meta.get("reference_type", "order")

    def get_order_id(self, obj: Notification) -> int | None:
        meta = NOTIFICATION_METADATA.get(obj.type.name, {})
        ref_type = meta.get("reference_type")
        if (
            ref_type == "order"
            or obj.type.name.startswith("order_")
            or "handover" in obj.type.name
            or "return" in obj.type.name
        ) and (obj.reference_id and str(obj.reference_id).isdigit()):
            return int(obj.reference_id)
        return None


class NotificationChannelPreferenceSerializer(serializers.Serializer):
    push = serializers.BooleanField(required=False, default=True)
    email = serializers.BooleanField(required=False, default=True)


class NotificationPreferencesSerializer(serializers.Serializer):
    """Serialize and validate user notification preference categories."""

    requests = NotificationChannelPreferenceSerializer(required=False)
    handover = NotificationChannelPreferenceSerializer(required=False)
    overdue = NotificationChannelPreferenceSerializer(required=False)
    messages = NotificationChannelPreferenceSerializer(required=False)
    reviews = NotificationChannelPreferenceSerializer(required=False)
    security = NotificationChannelPreferenceSerializer(required=False)
