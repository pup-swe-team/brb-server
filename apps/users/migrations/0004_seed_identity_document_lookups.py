"""
Seed the identity verification lookup tables for CP-105.

`identity_document_types` and `identity_document_statuses` are real tables
(DECISIONS.md D-02), but CP-105 cannot accept a submission until the rows exist
-- `document_type` and `status` are non-nullable PROTECT foreign keys. Admin
screens for populating them are not part of this ticket, so the two value sets
the ERD specifies are seeded here.

The values are written out literally instead of imported from
`apps.users.constants` on purpose: a migration has to keep producing the same
result even after the constants module is edited, and a live import would
silently rewrite history.
"""

from django.db import migrations

IDENTITY_DOCUMENT_TYPES = ["pup_id", "government_id"]
IDENTITY_DOCUMENT_STATUSES = ["pending", "approved", "rejected"]


def seed_lookup_tables(apps, schema_editor):
    IdentityDocumentType = apps.get_model("users", "IdentityDocumentType")
    IdentityDocumentStatus = apps.get_model("users", "IdentityDocumentStatus")

    for name in IDENTITY_DOCUMENT_TYPES:
        IdentityDocumentType.objects.get_or_create(name=name)

    for name in IDENTITY_DOCUMENT_STATUSES:
        IdentityDocumentStatus.objects.get_or_create(name=name)


def unseed_lookup_tables(apps, schema_editor):
    """
    Remove only the seeded rows, and only while nothing references them.

    The guards matter: if a submission exists, its `document_type`/`status` are
    PROTECT foreign keys and the delete would fail anyway, but failing with an
    IntegrityError mid-reverse is a far worse experience than skipping.
    """
    IdentityDocumentType = apps.get_model("users", "IdentityDocumentType")
    IdentityDocumentStatus = apps.get_model("users", "IdentityDocumentStatus")
    IdentityDocument = apps.get_model("users", "IdentityDocument")

    if not IdentityDocument.objects.exists():
        IdentityDocumentType.objects.filter(name__in=IDENTITY_DOCUMENT_TYPES).delete()
        IdentityDocumentStatus.objects.filter(
            name__in=IDENTITY_DOCUMENT_STATUSES
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_identitydocument_consent_given_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_lookup_tables, unseed_lookup_tables),
    ]
