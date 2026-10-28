from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0004_alter_dispute_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="cancel_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
