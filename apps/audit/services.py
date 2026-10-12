"""
Service layer for audit logging (CP-107, FR14).
"""

from typing import TYPE_CHECKING, Any

from .models import AdminAccessLog

if TYPE_CHECKING:
    from apps.users.models import IdentityDocument, User


def get_client_ip(request: Any) -> str | None:
    """Extract client IP from request, taking proxy headers into account safely."""
    if request is None or not hasattr(request, "META"):
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip or None


def log_admin_document_access(
    *,
    document: "IdentityDocument",
    admin: "User",
    action: str = "view",
    request: Any = None,
) -> AdminAccessLog:
    """
    Record an immutable audit log entry for FR14 compliance.

    Actions:
      - 'view': Opened the document in Django Admin
      - 'download': Downloaded document bytes via secure endpoint
      - 'review': Approved or rejected the document (CP-106)
      - 'contact_release': Accessed owner name/contact info (CP-107)
    """
    ip_address = get_client_ip(request)
    return AdminAccessLog.objects.create(
        document=document,
        admin=admin,
        action=action,
        ip_address=ip_address,
    )
