from django.contrib import admin
from django.utils import timezone

from .models import (
    AvailabilityWindow,
    BlockedDateRange,
    Listing,
    ListingCategory,
    ListingPhoto,
    ListingStatus,
    PickupLocation,
)


class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "lender",
        "title",
        "category",
        "condition",
        "status",
        "rate_per_day",
        "created_at",
    )
    list_filter = ("status", "category", "condition", "created_at", "updated_at")
    search_fields = ("title", "description", "lender__full_name", "lender__email")
    date_hierarchy = "created_at"


class ListingStatusAdmin(admin.ModelAdmin):
    """Lookup table seeded by fixtures/migrations; names are matched literally
    in the listing services (active, deactivated, deleted), so renames would
    silently break CP-401/402 behaviour (same rule as IdentityDocumentStatus)."""

    list_display = ("name",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ListingCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


class PickupLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "deleted_at")
    search_fields = ("name", "description")
    list_filter = ("deleted_at",)
    actions = ("soft_delete_selected",)

    @admin.action(description="Soft-delete selected pickup locations (CP-1105)")
    def soft_delete_selected(self, request, queryset) -> None:
        """Same semantics as DELETE /api/v1/pickup-locations/<id>/: stamp deleted_at."""
        count = queryset.filter(deleted_at__isnull=True).update(
            deleted_at=timezone.now()
        )
        self.message_user(request, f"Soft-deleted {count} pickup location(s).")


class ListingPhotoAdmin(admin.ModelAdmin):
    list_display = ("listing", "file_reference", "uploaded_at")
    search_fields = ("listing__title",)
    date_hierarchy = "uploaded_at"


class AvailabilityWindowAdmin(admin.ModelAdmin):
    list_display = ("listing", "start_date", "end_date")
    list_filter = ("start_date", "end_date")
    search_fields = ("listing__title",)


class BlockedDateRangeAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "order",
        "start_date",
        "end_date",
        "reason",
        "created_at",
    )
    list_filter = ("start_date", "end_date", "created_at")
    search_fields = ("listing__title", "reason")


admin.site.register(Listing, ListingAdmin)
admin.site.register(ListingStatus, ListingStatusAdmin)
admin.site.register(ListingCategory, ListingCategoryAdmin)
admin.site.register(PickupLocation, PickupLocationAdmin)
admin.site.register(ListingPhoto, ListingPhotoAdmin)
admin.site.register(AvailabilityWindow, AvailabilityWindowAdmin)
admin.site.register(BlockedDateRange, BlockedDateRangeAdmin)
