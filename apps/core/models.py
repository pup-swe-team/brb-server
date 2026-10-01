from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model providing self-updating created and modified fields."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SystemConfig(models.Model):
    """Platform-wide dynamic configuration parameters adjustable at runtime (FR14)."""

    config_key = models.CharField(max_length=100, primary_key=True)
    config_value = models.TextField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_configs"
        verbose_name = "System Configuration"
        verbose_name_plural = "System Configurations"

    def __str__(self) -> str:
        return f"{self.config_key}: {self.config_value[:50]}"
