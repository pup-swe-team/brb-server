from django.contrib import admin

from .models import Notification, NotificationPreference, NotificationType


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
    list_display = ("id", "user", "updated_at")
    search_fields = ("user__email", "user__full_name")
    raw_id_fields = ("user",)
