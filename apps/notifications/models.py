from django.conf import settings
from django.db import models


class NotificationType(models.Model):
    """
    Lookup table for in-app and email notification event types (FR11).
    Types: new_request, acceptance, decline, expiry, cancellation,
    code_generation, confirmed_handover, confirmed_return, upcoming_due_date,
    overdue_status, unreturned_status, new_message, new_review,
    verification_result, report_updates.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "notification_types"
        verbose_name = "Notification Type"
        verbose_name_plural = "Notification Types"

    def __str__(self) -> str:
        return self.name


class Notification(models.Model):
    """
    In-app event notification delivered to a user (FR11).
    reference_id points to the relevant order, listing, review, or report ID.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.ForeignKey(
        NotificationType,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    reference_id = models.CharField(max_length=100, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self) -> str:
        read_status = "Read" if self.is_read else "Unread"
        return f"{self.type.name} to {self.user.email} ({read_status})"
