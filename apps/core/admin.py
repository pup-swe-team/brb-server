from django.contrib import admin

from .models import SystemConfig


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    """
    Runtime-tunable platform settings (FR14).

    This is what makes CP-102's expiry window and CP-103's lockout threshold
    genuinely "Admin-configurable" rather than adjustable only from a shell. The
    keys the code reads are:

    - ``login_lockout_threshold``       (CP-103, default 5)
    - ``login_lockout_minutes``         (CP-103, default 15)
    - ``email_verification_expiry_days`` (CP-102, default 7)

    Values are stored as text and parsed by ``apps.core.selectors``; a
    non-numeric or missing value falls back to the default rather than raising,
    so a typo here degrades to the default instead of breaking login.
    """

    list_display = ("config_key", "config_value", "updated_by", "updated_at")
    search_fields = ("config_key", "config_value")
    readonly_fields = ("created_at", "updated_at")
    list_filter = ("updated_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("config_key")
