from django.conf import settings
from django.db import models

# --- Listing Reports ---


class ListingReportCategory(models.Model):
    """Category classification for reported listings (draw.io: listing_report_categories)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "listing_report_categories"
        verbose_name = "Listing Report Category"
        verbose_name_plural = "Listing Report Categories"

    def __str__(self) -> str:
        return self.name


class ListingReport(models.Model):
    """Report submitted against a resource listing (FR12)."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listing_reports",
    )
    target_listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    category = models.ForeignKey(
        ListingReportCategory,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    description = models.TextField()
    status = models.CharField(max_length=50, default="open")  # open, resolved
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_reports"
        verbose_name = "Listing Report"
        verbose_name_plural = "Listing Reports"

    def __str__(self) -> str:
        return f"Report #{self.id} on Listing #{self.target_listing_id} ({self.status})"


# --- User Reports ---


class UserReportCategory(models.Model):
    """Category classification for reported users (draw.io: user_report_categories)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "user_report_categories"
        verbose_name = "User Report Category"
        verbose_name_plural = "User Report Categories"

    def __str__(self) -> str:
        return self.name


class UserReport(models.Model):
    """
    Report submitted against a user profile (FR12).
    3 or more reports within rolling 30 days trigger priority admin review flag.
    """

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filed_user_reports",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_user_reports",
    )
    category = models.ForeignKey(
        UserReportCategory,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    description = models.TextField()
    status = models.CharField(max_length=50, default="open")  # open, resolved
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_reports"
        verbose_name = "User Report"
        verbose_name_plural = "User Reports"

    def __str__(self) -> str:
        return f"Report #{self.id} on {self.target_user.full_name} ({self.status})"


# --- Review Reports ---


class ReviewReportCategory(models.Model):
    """Category classification for reported reviews (draw.io: review_report_categories)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "review_report_categories"
        verbose_name = "Review Report Category"
        verbose_name_plural = "Review Report Categories"

    def __str__(self) -> str:
        return self.name


class ReviewReport(models.Model):
    """Report submitted against a rating or review comment (FR9, FR12)."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filed_review_reports",
    )
    target_review = models.ForeignKey(
        "reviews.Review",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    category = models.ForeignKey(
        ReviewReportCategory,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    description = models.TextField()
    status = models.CharField(max_length=50, default="open")  # open, resolved
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_reports"
        verbose_name = "Review Report"
        verbose_name_plural = "Review Reports"

    def __str__(self) -> str:
        return f"Report #{self.id} on Review #{self.target_review_id} ({self.status})"


# --- Message Reports ---


class MessageReportCategory(models.Model):
    """Category classification for reported chat messages (draw.io: message_report_categories)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "message_report_categories"
        verbose_name = "Message Report Category"
        verbose_name_plural = "Message Report Categories"

    def __str__(self) -> str:
        return self.name


class MessageReport(models.Model):
    """Report submitted against an abusive or fraudulent chat message (FR10, FR12)."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filed_message_reports",
    )
    target_message = models.ForeignKey(
        "chat.Message",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    category = models.ForeignKey(
        MessageReportCategory,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    description = models.TextField()
    status = models.CharField(max_length=50, default="open")  # open, resolved
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_reports"
        verbose_name = "Message Report"
        verbose_name_plural = "Message Reports"

    def __str__(self) -> str:
        return f"Report #{self.id} on Message #{self.target_message_id} ({self.status})"
