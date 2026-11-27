from django.contrib import admin

from .models import AdminAccessLog


@admin.register(AdminAccessLog)
class AdminAccessLogAdmin(admin.ModelAdmin):
    """Immutable audit trail (FR14, CP-1106). No add/edit/delete."""

    list_display = (
        "id",
        "action",
        "target_type",
        "target_id",
        "admin",
        "document",
        "ip_address",
        "accessed_at",
    )
    list_filter = ("action", "target_type", "accessed_at")
    search_fields = ("admin__email", "admin__full_name", "target_id", "details")
    readonly_fields = (
        "document",
        "admin",
        "action",
        "target_type",
        "target_id",
        "details",
        "ip_address",
        "accessed_at",
    )
    date_hierarchy = "accessed_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
