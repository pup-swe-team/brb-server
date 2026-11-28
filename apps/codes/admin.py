"""Django Admin configuration for authentication codes and attempt logs (CP-504, CP-505)."""

from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from .constants import CODE_STATUS_ACTIVE, CODE_STATUS_EXPIRED
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
        "used_at",
        "auth_status",
    )
    inlines = (AuthCodeAttemptInline,)
    actions = ("expire_selected_active_codes",)

    @admin.action(description="Expire selected active codes (set expired now)")
    def expire_selected_active_codes(self, request, queryset) -> None:
        """Backdate and expire selected active codes from /admin/ (QA / TC-067)."""
        now = timezone.now()
        expired_status, _ = AuthCodeStatus.objects.get_or_create(
            name=CODE_STATUS_EXPIRED
        )
        active_qs = queryset.filter(auth_status__name=CODE_STATUS_ACTIVE)
        updated = active_qs.update(
            auth_status=expired_status,
            generated_at=now - timedelta(hours=4),
            expires_at=now - timedelta(hours=1),
        )
        skipped = queryset.count() - updated
        msg = f"Expired {updated} active code(s)."
        if skipped:
            msg += f" {skipped} non-active code(s) skipped."
        self.message_user(request, msg)

    def save_model(self, request, obj, form, change) -> None:
        if (
            change
            and obj.auth_status.name == CODE_STATUS_ACTIVE
            and obj.expires_at <= timezone.now()
        ):
            expired_status, _ = AuthCodeStatus.objects.get_or_create(
                name=CODE_STATUS_EXPIRED
            )
            obj.auth_status = expired_status
        super().save_model(request, obj, form, change)

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
