from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class ImmutableAuditLogQuerySet(models.QuerySet):
    """Prevents bulk updates and bulk deletes on audit logs."""

    def delete(self):
        raise PermissionDenied("Audit log entries cannot be bulk-deleted.")

    def update(self, **kwargs):
        raise PermissionDenied("Audit log entries cannot be bulk-updated.")


class AdminAccessLog(models.Model):
    """
    Read-only, immutable audit log recording every administrator action
    and confidential document access (FR3, FR14, NFR 4.2, CP-1106).
    """

    document = models.ForeignKey(
        "users.IdentityDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_logs",
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="identity_document_access_logs",
    )
    action = models.CharField(
        max_length=50,
        default="view",
        help_text="Action performed: view, download, review, suspend, reinstate, ban, remove, resolve, config_update.",
    )
    target_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Target entity type, e.g. document, user, listing, review, report, config.",
    )
    target_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Identifier of the target entity.",
    )
    details = models.TextField(
        blank=True,
        default="",
        help_text="Additional context or path of the administrative action.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the administrator at the time of access.",
    )
    accessed_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableAuditLogQuerySet.as_manager()

    class Meta:
        db_table = "admin_access_logs"
        verbose_name = "Admin Access Log"
        verbose_name_plural = "Admin Access Logs"
        ordering = ["-accessed_at"]

    def __str__(self) -> str:
        target = (
            f" on {self.target_type} #{self.target_id}"
            if self.target_type
            else (f" on Document #{self.document_id}" if self.document_id else "")
        )
        return (
            f"{self.action.capitalize()}{target} "
            f"by {self.admin.full_name} at {self.accessed_at}"
        )

    def save(self, *args, **kwargs):
        if (
            self.pk
            and not kwargs.get("force_insert", False)
            and AdminAccessLog.objects.filter(pk=self.pk).exists()
        ):
            raise PermissionDenied(
                "Audit log entries are immutable and cannot be modified."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit log entries cannot be deleted.")
