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
