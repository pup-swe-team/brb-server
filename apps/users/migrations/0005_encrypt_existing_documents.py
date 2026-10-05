"""
Data migration for CP-107: encrypt existing identity document rows at rest.

If IDENTITY_DOCUMENT_ENCRYPTION_KEY is configured in settings, reads all
existing IdentityDocument rows, checks if they are already encrypted, and
encrypts any plaintext document_data bytes.

Reverse operation decrypts rows back to plaintext using the configured key.
"""

from django.conf import settings
from django.db import migrations


def encrypt_existing_documents(apps, schema_editor):
    key = getattr(settings, "IDENTITY_DOCUMENT_ENCRYPTION_KEY", "") or ""
    if not key:
        return

    from cryptography.fernet import Fernet, InvalidToken

    fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    IdentityDocument = apps.get_model("users", "IdentityDocument")

    for doc in IdentityDocument.objects.all():
        if not doc.document_data:
            continue
        data = bytes(doc.document_data)
        try:
            fernet.decrypt(data)
            continue
        except (InvalidToken, Exception):
            pass

        encrypted = fernet.encrypt(data)
        doc.document_data = encrypted
        doc.save(update_fields=["document_data"])


def decrypt_existing_documents(apps, schema_editor):
    key = getattr(settings, "IDENTITY_DOCUMENT_ENCRYPTION_KEY", "") or ""
    if not key:
        return

    from cryptography.fernet import Fernet, InvalidToken

    fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    IdentityDocument = apps.get_model("users", "IdentityDocument")

    for doc in IdentityDocument.objects.all():
        if not doc.document_data:
            continue
        data = bytes(doc.document_data)
        try:
            decrypted = fernet.decrypt(data)
            doc.document_data = decrypted
            doc.save(update_fields=["document_data"])
        except (InvalidToken, Exception):
            pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_seed_identity_document_lookups"),
    ]

    operations = [
        migrations.RunPython(
            encrypt_existing_documents,
            decrypt_existing_documents,
        ),
    ]
