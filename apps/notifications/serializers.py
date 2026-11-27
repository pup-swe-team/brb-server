"""Serializers for the notifications domain (FR11, CP-801, CP-802)."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .constants import (
    CLIENT_CHANNEL_KEYS,
    CLIENT_CHANNEL_TO_CATEGORY_MAP,
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


def serialize_notification_preferences(
    prefs: dict[str, bool],
    channels: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    """Build the CP-802 preferences response with top-level booleans, metadata, and channel toggles."""
    if channels is None:
        channels = {}
        for key in CLIENT_CHANNEL_KEYS:
            if key == "security":
                channels[key] = {"push": True, "email": True}
            else:
                category = CLIENT_CHANNEL_TO_CATEGORY_MAP[key]
                channels[key] = {"push": True, "email": bool(prefs.get(category, True))}

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
        "channels": channels,
    }


def _parse_preference_value(raw_val: Any) -> bool | dict[str, bool] | None:
    if isinstance(raw_val, bool):
        return raw_val
    if isinstance(raw_val, dict):
        parsed_channel: dict[str, bool] = {}
        for channel_key, normalized_key in (
            ("push", "push"),
            ("push_enabled", "push"),
            ("email", "email"),
            ("email_enabled", "email"),
        ):
            if channel_key in raw_val:
                if not isinstance(raw_val[channel_key], bool):
                    return None
                parsed_channel[normalized_key] = raw_val[channel_key]
        if parsed_channel:
            return parsed_channel
    return None


class NotificationPreferencesSerializer(serializers.Serializer):
    """
    Validate CP-802 notification preferences across the 4 canonical categories
    (`order_updates`, `messages`, `reviews`, `account_verification`) as well as
    brb-client's 6 `{push, email}` groups (`requests`, `handover`, `overdue`,
    `messages`, `reviews`, `security`).
    """

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Preferences payload must be a JSON object."}
            )

        items_to_parse: dict[str, Any] = {}
        for raw_key, raw_val in data.items():
            if str(raw_key).strip().lower() == "channels" and isinstance(raw_val, dict):
                items_to_parse.update(raw_val)
            else:
                items_to_parse[str(raw_key)] = raw_val

        parsed: dict[str, Any] = {}
        errors: dict[str, str] = {}

        for raw_key, raw_val in items_to_parse.items():
            clean_key = str(raw_key).strip().lower()
            if clean_key in CLIENT_CHANNEL_KEYS:
                target_key = clean_key
            else:
                target_key = PREFERENCE_CATEGORY_ALIASES.get(clean_key)

            if target_key is None:
                allowed = ", ".join(
                    (
                        *DEFAULT_EMAIL_NOTIFICATION_PREFERENCES.keys(),
                        *CLIENT_CHANNEL_KEYS,
                    )
                )
                errors[str(raw_key)] = (
                    f"Unknown notification preference category '{raw_key}'. "
                    f"Allowed categories: {allowed}."
                )
                continue

            parsed_val = _parse_preference_value(raw_val)
            if parsed_val is None:
                errors[str(raw_key)] = (
                    "Preference value must be a boolean or an object with boolean 'push'/'email' fields."
                )
                continue

            parsed[target_key] = parsed_val

        if errors:
            raise serializers.ValidationError(errors)

        return parsed
