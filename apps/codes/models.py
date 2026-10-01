from django.conf import settings
from django.db import models


class AuthCodeType(models.Model):
    """Authentication code type lookup table (draw.io: auth_code_types: handover, return)."""

    name = models.CharField(max_length=50, unique=True)  # handover, return

    class Meta:
        db_table = "auth_code_types"
        verbose_name = "Auth Code Type"
        verbose_name_plural = "Auth Code Types"

    def __str__(self) -> str:
        return self.name


class AuthCodeStatus(models.Model):
    """Authentication code status lookup table (draw.io: auth_code_statuses: active, used, expired)."""

    name = models.CharField(max_length=50, unique=True)  # active, used, expired

    class Meta:
        db_table = "auth_code_statuses"
        verbose_name = "Auth Code Status"
        verbose_name_plural = "Auth Code Statuses"

    def __str__(self) -> str:
        return self.name


class AuthCode(models.Model):
    """
    Single-use, 6-digit time-limited OTP for handover or return verification (FR8, NFR 4.4).
    Handover: Generated for Lender -> entered by Borrower.
    Return: Generated for Borrower -> entered by Lender.
    """

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="auth_codes",
    )
    code_type = models.ForeignKey(
        AuthCodeType,
        on_delete=models.PROTECT,
        related_name="codes",
    )
    code_value = models.CharField(max_length=6)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    auth_status = models.ForeignKey(
        AuthCodeStatus,
        on_delete=models.PROTECT,
        related_name="codes",
    )

    class Meta:
        db_table = "auth_codes"
        verbose_name = "Auth Code"
        verbose_name_plural = "Auth Codes"

    def __str__(self) -> str:
        return f"{self.code_type.name.capitalize()} Code for Order #{self.order_id} ({self.auth_status.name})"


class AuthCodeAttempt(models.Model):
    """
    Log of each code entry attempt to prevent brute-forcing and enforce lockout (FR8, NFR 4.4).
    """

    code = models.ForeignKey(
        AuthCode,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="auth_code_attempts",
    )
    was_successful = models.BooleanField(default=False)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_code_attempts"
        verbose_name = "Auth Code Attempt"
        verbose_name_plural = "Auth Code Attempts"

    def __str__(self) -> str:
        status_text = "Success" if self.was_successful else "Failed"
        return f"{status_text} attempt on Code #{self.code_id} by {self.attempted_by.full_name}"
