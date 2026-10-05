from django.db import migrations, models


def demote_admin_affiliation_to_is_staff(apps, schema_editor):
    """
    `Admin` is being removed from `users.affiliation`; administrator authority
    now lives in `is_staff` (see DECISIONS.md D-03).

    Any pre-existing row still carrying `affiliation = "Admin"` must keep its
    administrative capability, so promote it to `is_staff` and re-align
    `affiliation` with a real PUP role. Without this, such rows would keep an
    invalid choice that fails model validation.
    """
    User = apps.get_model("users", "User")
    User.objects.filter(affiliation="Admin").update(
        is_staff=True, affiliation="Faculty"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            demote_admin_affiliation_to_is_staff, migrations.RunPython.noop
        ),
        migrations.AlterField(
            model_name="user",
            name="affiliation",
            field=models.CharField(
                choices=[("Student", "Student"), ("Faculty", "Faculty"), ("Staff", "Staff")],
                default="Student",
                max_length=20,
            ),
        ),
    ]
