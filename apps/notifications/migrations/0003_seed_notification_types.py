"""Seed notification type lookup table (FR11, CP-106)."""

from django.db import migrations

NOTIFICATION_TYPES = [
    "new_request",
    "acceptance",
    "decline",
    "expiry",
    "cancellation",
    "code_generation",
    "confirmed_handover",
    "confirmed_return",
    "upcoming_due_date",
    "overdue_status",
    "unreturned_status",
    "new_message",
    "new_review",
    "verification_result",
    "report_updates",
]


def seed_notification_types(apps, schema_editor):
    NotificationType = apps.get_model("notifications", "NotificationType")
    for name in NOTIFICATION_TYPES:
        NotificationType.objects.get_or_create(name=name)


def unseed_notification_types(apps, schema_editor):
    NotificationType = apps.get_model("notifications", "NotificationType")
    Notification = apps.get_model("notifications", "Notification")

    if not Notification.objects.exists():
        NotificationType.objects.filter(name__in=NOTIFICATION_TYPES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed_notification_types, unseed_notification_types),
    ]
