# Register your models here.
from django.contrib import admin

from .models import Listing, PickupLocation


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
    list_display = (
        "name",
        "description",
        "deleted_at",
    )
    search_fields = ("name",)


admin.site.register(Listing, ListingAdmin)
admin.site.register(PickupLocation, PickupLocationAdmin)
