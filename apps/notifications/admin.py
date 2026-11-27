from django.contrib import admin

from .constants import (
    PREF_CATEGORY_ACCOUNT_VERIFICATION,
    PREF_CATEGORY_MESSAGES,
    PREF_CATEGORY_ORDER_UPDATES,
    PREF_CATEGORY_REVIEWS,
)
from .models import Notification, NotificationPreference, NotificationType
from .services import _normalize_stored_preferences


@admin.register(NotificationType)
class NotificationTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "type", "reference_id", "is_read", "created_at")
    list_filter = ("is_read", "type")
    search_fields = ("user__email", "user__full_name", "reference_id")
    raw_id_fields = ("user",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "order_updates_email",
        "messages_email",
        "reviews_email",
        "account_verification_email",
        "updated_at",
    )
    search_fields = ("user__email", "user__full_name")
    raw_id_fields = ("user",)

    @admin.display(boolean=True, description="Order Updates")
    def order_updates_email(self, obj: NotificationPreference) -> bool:
        return _normalize_stored_preferences(obj.preferences)[
            PREF_CATEGORY_ORDER_UPDATES
        ]

    @admin.display(boolean=True, description="Messages")
    def messages_email(self, obj: NotificationPreference) -> bool:
        return _normalize_stored_preferences(obj.preferences)[PREF_CATEGORY_MESSAGES]

    @admin.display(boolean=True, description="Reviews")
    def reviews_email(self, obj: NotificationPreference) -> bool:
        return _normalize_stored_preferences(obj.preferences)[PREF_CATEGORY_REVIEWS]

    @admin.display(boolean=True, description="Account & Verification")
    def account_verification_email(self, obj: NotificationPreference) -> bool:
        return _normalize_stored_preferences(obj.preferences)[
            PREF_CATEGORY_ACCOUNT_VERIFICATION
        ]
