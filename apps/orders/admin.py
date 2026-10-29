"""Django Admin registrations for orders, status overrides, disputes, and unreturned cases (CP-506)."""

from django.contrib import admin

from .models import (
    Dispute,
    DisputeEvidence,
    FileType,
    Order,
    OrderStatus,
    OrderStatusOverride,
    UnreturnedCase,
    UnreturnedCaseStatus,
)


@admin.register(OrderStatus)
class OrderStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(UnreturnedCaseStatus)
class UnreturnedCaseStatusAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(FileType)
class FileTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


class OrderStatusOverrideInline(admin.TabularInline):
    model = OrderStatusOverride
    extra = 0
    can_delete = False
    readonly_fields = (
        "admin",
        "previous_status",
        "new_status",
        "reason",
        "overridden_at",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "listing",
        "borrower",
        "start_date",
        "end_date",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("listing__title", "borrower__email", "borrower__full_name")
    inlines = (OrderStatusOverrideInline,)


@admin.register(OrderStatusOverride)
class OrderStatusOverrideAdmin(admin.ModelAdmin):
    """Read-only audit log of manual administrator order status overrides (FR8, FR14)."""

    list_display = (
        "id",
        "order",
        "admin",
        "previous_status",
        "new_status",
        "overridden_at",
    )
    list_filter = ("previous_status", "new_status")
    search_fields = ("order__id", "admin__email", "reason")
    readonly_fields = (
        "order",
        "admin",
        "previous_status",
        "new_status",
        "reason",
        "overridden_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(UnreturnedCase)
class UnreturnedCaseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "status",
        "escalated_at",
        "escalated_by",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "order__id",
        "order__borrower__email",
        "order__borrower__full_name",
        "resolution_notes",
    )


class DisputeEvidenceInline(admin.TabularInline):
    model = DisputeEvidence
    extra = 0
    readonly_fields = ("submitted_by", "file_reference", "file_type", "uploaded_at")


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "raised_by", "status", "resolved_by", "created_at")
    list_filter = ("status",)
    search_fields = ("order__id", "description", "resolution_notes")
    inlines = (DisputeEvidenceInline,)


@admin.register(DisputeEvidence)
class DisputeEvidenceAdmin(admin.ModelAdmin):
    list_display = ("id", "dispute", "submitted_by", "file_type", "uploaded_at")
    list_filter = ("file_type",)
