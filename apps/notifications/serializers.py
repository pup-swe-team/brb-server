"""Serializers for the notifications domain (FR11, CP-801, CP-802)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .constants import (
    DEFAULT_EMAIL_NOTIFICATION_PREFERENCES,
    NOTIFICATION_METADATA,
    NOTIFICATION_PREFERENCE_CATEGORIES,
    ORDER_PREFIXED_NOTIFICATION_TYPES,
    PREF_CATEGORY_ACCOUNT_VERIFICATION,
    PREF_CATEGORY_MESSAGES,
    PREF_CATEGORY_ORDER_UPDATES,
    PREF_CATEGORY_REVIEWS,
    PREFERENCE_CATEGORY_ALIASES,
)
from .models import Notification


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
        if obj.reference_id and obj.type.name in ORDER_PREFIXED_NOTIFICATION_TYPES:
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


def serialize_notification_preferences(prefs: dict[str, bool]) -> dict[str, Any]:
    """Build the CP-802 preferences response with both top-level booleans and category metadata."""
    return {
        PREF_CATEGORY_ORDER_UPDATES: bool(prefs.get(PREF_CATEGORY_ORDER_UPDATES, True)),
        PREF_CATEGORY_MESSAGES: bool(prefs.get(PREF_CATEGORY_MESSAGES, True)),
        PREF_CATEGORY_REVIEWS: bool(prefs.get(PREF_CATEGORY_REVIEWS, True)),
        PREF_CATEGORY_ACCOUNT_VERIFICATION: bool(
            prefs.get(PREF_CATEGORY_ACCOUNT_VERIFICATION, True)
        ),
        "categories": [
            {
                "key": key,
                "label": label,
                "description": description,
                "email_enabled": bool(prefs.get(key, True)),
            }
            for key, label, description in NOTIFICATION_PREFERENCE_CATEGORIES
        ],
    }


class NotificationPreferencesSerializer(serializers.Serializer):
    """
    Validate CP-802 email notification preferences across the four categories:
    order_updates, messages, reviews, and account_verification.

    Accepts flat booleans (e.g. `{"messages": false}`) or channel dicts
    (e.g. `{"messages": {"email": false}}`) as well as display-name aliases.
    """

    def to_internal_value(self, data: Any) -> dict[str, bool]:
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Preferences payload must be a JSON object."}
            )

        parsed: dict[str, bool] = {}
        errors: dict[str, str] = {}

        for raw_key, raw_val in data.items():
            normalized_key = PREFERENCE_CATEGORY_ALIASES.get(
                str(raw_key).strip().lower()
            )
            if normalized_key is None:
                allowed = ", ".join(DEFAULT_EMAIL_NOTIFICATION_PREFERENCES.keys())
                errors[str(raw_key)] = (
                    f"Unknown notification preference category '{raw_key}'. "
                    f"Allowed categories: {allowed}."
                )
                continue

            if isinstance(raw_val, bool):
                parsed[normalized_key] = raw_val
            elif isinstance(raw_val, dict):
                if "email" in raw_val and isinstance(raw_val["email"], bool):
                    parsed[normalized_key] = raw_val["email"]
                elif "email_enabled" in raw_val and isinstance(
                    raw_val["email_enabled"], bool
                ):
                    parsed[normalized_key] = raw_val["email_enabled"]
                else:
                    errors[str(raw_key)] = (
                        "Must provide a boolean or an object with a boolean 'email' field."
                    )
            else:
                errors[str(raw_key)] = (
                    "Preference value must be a boolean (true/false)."
                )

        if errors:
            raise serializers.ValidationError(errors)

        return parsed
