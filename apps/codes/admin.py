"""Django Admin configuration for authentication codes and attempt logs (CP-504, CP-505)."""

from django.contrib import admin

from .models import AuthCode, AuthCodeAttempt, AuthCodeStatus, AuthCodeType


@admin.register(AuthCodeType)
class AuthCodeTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(AuthCodeStatus)
class AuthCodeStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


class AuthCodeAttemptInline(admin.TabularInline):
    model = AuthCodeAttempt
    extra = 0
    can_delete = False
    readonly_fields = ("attempted_by", "was_successful", "attempted_at")

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AuthCode)
class AuthCodeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "code_type",
        "auth_status",
        "generated_at",
        "expires_at",
        "used_at",
    )
    list_filter = ("code_type", "auth_status")
    search_fields = ("order__id", "code_value")
    readonly_fields = (
        "order",
        "code_type",
        "code_value",
        "generated_at",
        "expires_at",
        "used_at",
        "auth_status",
    )
    inlines = (AuthCodeAttemptInline,)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AuthCodeAttempt)
class AuthCodeAttemptAdmin(admin.ModelAdmin):
    """Read-only audit log of authentication code entry attempts (FR8, FR14)."""

    list_display = ("id", "code", "attempted_by", "was_successful", "attempted_at")
    list_filter = ("was_successful", "code__code_type")
    search_fields = (
        "code__order__id",
        "attempted_by__email",
        "attempted_by__full_name",
    )
    readonly_fields = ("code", "attempted_by", "was_successful", "attempted_at")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
