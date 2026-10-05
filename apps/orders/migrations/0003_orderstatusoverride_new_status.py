import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_new_status(apps, schema_editor):
    """
    Pre-existing overrides cannot have a known target status, so fall back to
    the order's current status (the admin's correction is presumed to have
    already been applied).
    """
    OrderStatusOverride = apps.get_model("orders", "OrderStatusOverride")
    for override in OrderStatusOverride.objects.select_related("order").iterator():
        if override.new_status is None:
            override.new_status = override.order.status.name
            override.save(update_fields=["new_status"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderstatusoverride",
            name="new_status",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.RunPython(backfill_new_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="orderstatusoverride",
            name="new_status",
            field=models.CharField(max_length=50),
        ),
    ]
