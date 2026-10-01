from django.conf import settings
from django.db import models


class OrderStatus(models.Model):
    """
    Order status lookup table (draw.io: order_statuses).
    Values: requested, confirmed, active, returned, completed,
    declined, expired, cancelled, overdue, unreturned, disputed.
    """

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = "order_statuses"
        verbose_name = "Order Status"
        verbose_name_plural = "Order Statuses"

    def __str__(self) -> str:
        return self.name


class Order(models.Model):
    """
    Borrowing transaction tracking an educational resource between Borrower and Lender (FR8).
    Payment, if applicable, is arranged outside the platform.
    """

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="borrowed_orders",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.ForeignKey(
        OrderStatus,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"
        verbose_name = "Order"
        verbose_name_plural = "Orders"

    def __str__(self) -> str:
        return f"Order #{self.id} - {self.listing.title} ({self.status.name})"


class OrderStatusOverride(models.Model):
    """
    Audit log of manual administrator status corrections when transactions get stuck (FR8, FR14).
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_overrides",
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="order_status_overrides",
    )
    previous_status = models.CharField(max_length=50)
    reason = models.TextField()
    overridden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_status_overrides"
        verbose_name = "Order Status Override"
        verbose_name_plural = "Order Status Overrides"

    def __str__(self) -> str:
        return f"Override Order #{self.order_id} by {self.admin.full_name}"


class FileType(models.Model):
    """Evidence file format lookup table (draw.io: file_types: photo, video)."""

    name = models.CharField(max_length=20, unique=True)  # photo, video

    class Meta:
        db_table = "file_types"
        verbose_name = "File Type"
        verbose_name_plural = "File Types"

    def __str__(self) -> str:
        return self.name


class Dispute(models.Model):
    """
    Damage or missing parts dispute raised by the Lender upon return (FR8).
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="disputes",
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="raised_disputes",
    )
    description = models.TextField()
    borrower_response = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=50, default="open"
    )  # open, resolved, escalated
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_disputes",
    )
    resolution_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "disputes"
        verbose_name = "Dispute"
        verbose_name_plural = "Disputes"

    def __str__(self) -> str:
        return f"Dispute on Order #{self.order_id} ({self.status})"


class DisputeEvidence(models.Model):
    """Photo or video documentation submitted during damage disputes (FR8)."""

    dispute = models.ForeignKey(
        Dispute,
        on_delete=models.CASCADE,
        related_name="evidences",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_dispute_evidences",
    )
    file_reference = models.FileField(upload_to="dispute_evidences/")
    file_type = models.ForeignKey(
        FileType,
        on_delete=models.PROTECT,
        related_name="dispute_evidences",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dispute_evidences"
        verbose_name = "Dispute Evidence"
        verbose_name_plural = "Dispute Evidences"

    def __str__(self) -> str:
        return f"Evidence for Dispute #{self.dispute_id} ({self.file_type.name})"


class UnreturnedCaseStatus(models.Model):
    """Case progress lookup table (draw.io: unreturned_cases_statuses)."""

    name = models.CharField(
        max_length=50, unique=True
    )  # open, escalated, returned, unresolved

    class Meta:
        db_table = "unreturned_cases_statuses"
        verbose_name = "Unreturned Case Status"
        verbose_name_plural = "Unreturned Case Statuses"

    def __str__(self) -> str:
        return self.name


class UnreturnedCase(models.Model):
    """
    Administrative trace case for items overdue past the threshold (FR8).
    Facilitates formal escalation to PUP OSS or Campus Security.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="unreturned_cases",
    )
    status = models.ForeignKey(
        UnreturnedCaseStatus,
        on_delete=models.PROTECT,
        related_name="cases",
    )
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="escalated_unreturned_cases",
    )
    resolution_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "unreturned_cases"
        verbose_name = "Unreturned Case"
        verbose_name_plural = "Unreturned Cases"

    def __str__(self) -> str:
        return f"Unreturned Case - Order #{self.order_id} ({self.status.name})"
