from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def hold_existing_revocations(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(lender_status="revoked").update(lender_reapplication_hold=True)


class Migration(migrations.Migration):
    dependencies = [("users", "0007_user_email_change_sent_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="lender_reapplication_hold",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="LenderRevocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("self", "Self"), ("admin", "Admin")], max_length=10)),
                ("reason", models.CharField(blank=True, choices=[("repeated_late_returns", "Repeated late returns"), ("repeated_reports_complaints", "Repeated reports or complaints"), ("policy_violation", "Policy violation"), ("other", "Other")], max_length=40)),
                ("detail", models.TextField(blank=True)),
                ("revoked_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="performed_lender_revocations", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lender_revocations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "lender_revocations", "ordering": ["-revoked_at", "-pk"]},
        ),
        migrations.RunPython(hold_existing_revocations, migrations.RunPython.noop),
    ]
