from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0005_order_cancel_reason")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="decline_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
