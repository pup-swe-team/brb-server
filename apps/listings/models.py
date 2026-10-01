from django.conf import settings
from django.db import models


class ListingStatus(models.Model):
    """Listing status lookup table (draw.io: listing_statuses)."""

    name = models.CharField(max_length=50, unique=True)  # active, deactivated, deleted

    class Meta:
        db_table = "listing_statuses"
        verbose_name = "Listing Status"
        verbose_name_plural = "Listing Statuses"

    def __str__(self) -> str:
        return self.name


class ListingCategory(models.Model):
    """Resource category classification (e.g. Textbooks, Reviewers, Calculators, Lab Equipment)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        db_table = "listing_categories"
        verbose_name = "Listing Category"
        verbose_name_plural = "Listing Categories"

    def __str__(self) -> str:
        return self.name


class PickupLocation(models.Model):
    """Designated campus meetup locations approved by administrators (FR7, FR14)."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "pickup_locations"
        verbose_name = "Pickup Location"
        verbose_name_plural = "Pickup Locations"

    def __str__(self) -> str:
        return self.name


class Listing(models.Model):
    """Educational resource posted by a verified Lender (FR5, FR6, FR7)."""

    lender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listings",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(
        ListingCategory,
        on_delete=models.PROTECT,
        related_name="listings",
    )
    condition = models.CharField(max_length=50)  # e.g., Brand New, Like New, Good, Fair
    pickup_location = models.ForeignKey(
        PickupLocation,
        on_delete=models.PROTECT,
        related_name="listings",
    )
    rate_per_day = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )  # Null if offered for free
    is_ownership_confirmed = models.BooleanField(default=False)
    status = models.ForeignKey(
        ListingStatus,
        on_delete=models.PROTECT,
        related_name="listings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listings"
        verbose_name = "Listing"
        verbose_name_plural = "Listings"

    def __str__(self) -> str:
        return f"{self.title} (by {self.lender.full_name})"


class ListingPhoto(models.Model):
    """Supporting photographs of a resource listing (FR7)."""

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    file_reference = models.CharField(max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_photos"
        verbose_name = "Listing Photo"
        verbose_name_plural = "Listing Photos"

    def __str__(self) -> str:
        return f"Photo for {self.listing.title} ({self.id})"


class AvailabilityWindow(models.Model):
    """Lender-defined calendar availability window for a resource (FR7)."""

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="availability_windows",
    )
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        db_table = "availability_windows"
        verbose_name = "Availability Window"
        verbose_name_plural = "Availability Windows"

    def __str__(self) -> str:
        return f"{self.listing.title}: {self.start_date} to {self.end_date}"
