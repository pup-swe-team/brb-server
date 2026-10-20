from django.contrib import admin

from .models import BlockedDateRange, Listing, PickupLocation


class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "lender",
        "title",
        "description",
        "category",
    )
    list_filter = ("created_at", "updated_at")
    search_fields = ("title", "description")


class PickupLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "deleted_at")
    search_fields = ("name", "description")
    list_filter = ("deleted_at",)


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
admin.site.register(PickupLocation, PickupLocationAdmin)
admin.site.register(BlockedDateRange, BlockedDateRangeAdmin)
