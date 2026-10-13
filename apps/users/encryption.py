"""
Symmetric encryption for identity document bytes (CP-107).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
The key is read from settings at call time, not at import time, so tests
can override it with @override_settings.

If no key is configured in development or test environments, the bytes
pass through unchanged. In production (DEBUG=False with non-SQLite database),
a missing key raises ImproperlyConfigured to fail closed (NFR 4.2).
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "InvalidToken",
    "decrypt_document_data",
    "detect_document_content_type",
    "encrypt_document_data",
    "get_fernet",
]

# Signature sniffing for the three formats the identity document upload accepts
# (JPEG, PNG, PDF). Kept here next to encryption because both deal with the raw
# stored bytes; the download view and the portal document preview share it so
# the two never disagree about what kind of file a submission is.
_DOCUMENT_MAGIC_NUMBERS = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"%PDF", "application/pdf", ".pdf"),
)


def detect_document_content_type(raw_bytes: bytes) -> tuple[str, str]:
    """
    Infer (content_type, extension) for identity document bytes from their header.

    Falls back to (application/octet-stream, .bin) when no signature matches, so
    callers always get a usable pair.
    """
    for signature, content_type, extension in _DOCUMENT_MAGIC_NUMBERS:
        if raw_bytes.startswith(signature):
            return content_type, extension
    return "application/octet-stream", ".bin"


def get_fernet() -> Fernet | None:
    """
    Return a Fernet instance configured from settings, or None if unconfigured.

    Raises ImproperlyConfigured if in production and key is missing, or if the
    key is invalid.
    """
    key = getattr(settings, "IDENTITY_DOCUMENT_ENCRYPTION_KEY", "") or ""
    if isinstance(key, bytes):
        key = key.decode("utf-8")
    key = key.strip()

    if not key:
        is_prod = not getattr(settings, "DEBUG", False) and "sqlite" not in getattr(
            settings, "DATABASES", {}
        ).get("default", {}).get("ENGINE", "")
        if is_prod:
            raise ImproperlyConfigured(
                "IDENTITY_DOCUMENT_ENCRYPTION_KEY must be configured in production."
            )
        return None

    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ImproperlyConfigured(
            f"Invalid IDENTITY_DOCUMENT_ENCRYPTION_KEY: {exc}"
        ) from exc


def encrypt_document_data(plaintext: bytes | memoryview | None) -> bytes:
    """
    Encrypt raw document bytes using Fernet.

    Returns ciphertext bytes, or original bytes if no key is configured in dev/test.
    """
    if plaintext is None:
        return b""
    raw_bytes = bytes(plaintext)
    if not raw_bytes:
        return b""

    fernet = get_fernet()
    if fernet is None:
        return raw_bytes
    return fernet.encrypt(raw_bytes)


def decrypt_document_data(ciphertext: bytes | memoryview | None) -> bytes:
    """
    Decrypt document bytes using Fernet.

    Returns decrypted plaintext bytes, or original bytes if no key is configured
    in dev/test. Raises InvalidToken if ciphertext is invalid, tampered with, or
    encrypted with a different key.
    """
    if ciphertext is None:
        return b""
    raw_bytes = bytes(ciphertext)
    if not raw_bytes:
        return b""

    fernet = get_fernet()
    if fernet is None:
        return raw_bytes
    return fernet.decrypt(raw_bytes)
