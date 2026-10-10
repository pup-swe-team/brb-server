# Register your models here.
from django.contrib import admin

from .models import Listing


class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "lender",
        "title",
        "description",
        "category",
    )
    list_filter = ("created_at", "updated_at")
    search_fields = ("title", "description")


admin.site.register(Listing, ListingAdmin)
