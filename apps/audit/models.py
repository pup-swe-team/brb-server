from django.conf import settings
from django.db import models


class AdminAccessLog(models.Model):
    """
    Read-only audit log recording every administrator access or download of
    confidential identity verification documents (FR3, FR14, NFR 4.2).
    """

    document = models.ForeignKey(
        "users.IdentityDocument",
        on_delete=models.CASCADE,
        related_name="access_logs",
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="identity_document_access_logs",
    )
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_access_logs"
        verbose_name = "Admin Access Log"
        verbose_name_plural = "Admin Access Logs"

    def __str__(self) -> str:
        return f"Document #{self.document_id} accessed by {self.admin.full_name} at {self.accessed_at}"


class AdminActionLog(models.Model):
    """
    Immutable audit log recording platform moderation and configuration changes (FR14).
    Captures actions like user suspensions, bans, listing removals, dispute resolutions,
    and parameter adjustments.
    """

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="action_logs",
    )
    action = models.CharField(max_length=100)
    target_model = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100)
    notes = models.TextField(blank=True, default="")
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_action_logs"
        verbose_name = "Admin Action Log"
        verbose_name_plural = "Admin Action Logs"

    def __str__(self) -> str:
        return f"{self.action} on {self.target_model}:{self.target_id} by {self.admin.full_name}"
