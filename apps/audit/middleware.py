import logging
import re
from collections.abc import Callable
from typing import ClassVar

from django.http import HttpRequest, HttpResponse

from .models import AdminAccessLog
from .services import get_client_ip

logger = logging.getLogger(__name__)


class AdminActionLoggingMiddleware:
    """
    CP-1106 / FR14 / TC-115: Automatically records an immutable audit log entry
    for every administrator action (mutating requests across /portal/, /api/v1/admin/,
    and /admin/, plus document inspection and download views).
    """

    # URL patterns to detect specific admin actions, target types, and IDs
    PATTERNS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        # Verification document views and reviews
        (
            r"^/portal/verification/(?P<id>\d+)/review/$",
            "review_document",
            "document",
        ),
        (r"^/portal/verification/(?P<id>\d+)/$", "view_document", "document"),
        (
            r"^/api/v1/identity/(?P<id>\d+)/download/$",
            "download_document",
            "document",
        ),
        (
            r"^/api/v1/identity/(?P<id>\d+)/review/$",
            "review_document",
            "document",
        ),
        # User moderation
        (r"^/portal/users/(?P<id>\d+)/suspend/$", "suspend_user", "user"),
        (
            r"^/api/v1/(?:admin/)?users/(?P<id>\d+)/suspend/$",
            "suspend_user",
            "user",
        ),
        (r"^/portal/users/(?P<id>\d+)/reinstate/$", "reinstate_user", "user"),
        (
            r"^/api/v1/(?:admin/)?users/(?P<id>\d+)/reinstate/$",
            "reinstate_user",
            "user",
        ),
        (r"^/portal/users/(?P<id>\d+)/ban/$", "ban_user", "user"),
        (r"^/api/v1/(?:admin/)?users/(?P<id>\d+)/ban/$", "ban_user", "user"),
        (
            r"^/portal/users/(?P<id>\d+)/revoke-lender/$",
            "revoke_lender",
            "user",
        ),
        (
            r"^/api/v1/users/(?P<id>\d+)/revoke-lender/$",
            "revoke_lender",
            "user",
        ),
        (
            r"^/portal/users/(?P<id>\d+)/confirm-flag/$",
            "confirm_user_flag",
            "user",
        ),
        (
            r"^/api/v1/(?:admin/)?users/(?P<id>\d+)/confirm-flag/$",
            "confirm_user_flag",
            "user",
        ),
        (
            r"^/portal/users/(?P<id>\d+)/dismiss-flag/$",
            "dismiss_user_flag",
            "user",
        ),
        (
            r"^/api/v1/(?:admin/)?users/(?P<id>\d+)/dismiss-flag/$",
            "dismiss_user_flag",
            "user",
        ),
        (
            r"^/portal/users/(?P<id>\d+)/clear-lender-hold/$",
            "clear_lender_hold",
            "user",
        ),
        # Content moderation
        (r"^/portal/listings/(?P<id>\d+)/remove/$", "remove_listing", "listing"),
        (
            r"^/api/v1/admin/listings/(?P<id>\d+)/$",
            "remove_listing",
            "listing",
        ),
        (r"^/portal/reviews/(?P<id>\d+)/remove/$", "remove_review", "review"),
        (r"^/api/v1/admin/reviews/(?P<id>\d+)/$", "remove_review", "review"),
        # Reports resolution
        (
            r"^/portal/reports/(?P<type>[^/]+)/(?P<id>\d+)/resolve/$",
            "resolve_report",
            "report",
        ),
        # Configuration
        (
            r"^/portal/system-parameters/$",
            "update_system_parameters",
            "system_config",
        ),
        (
            r"^/api/v1/admin/configs/(?P<id>[^/]+)/$",
            "update_system_config",
            "system_config",
        ),
        (
            r"^/api/v1/admin/configs/$",
            "bulk_update_system_configs",
            "system_config",
        ),
        # Pickup locations & categories
        (
            r"^/portal/pickup-locations/(?P<id>\d+)/delete/$",
            "delete_pickup_location",
            "pickup_location",
        ),
        (
            r"^/portal/pickup-locations/(?P<id>\d+)/restore/$",
            "restore_pickup_location",
            "pickup_location",
        ),
        (
            r"^/portal/categories/(?P<id>\d+)/delete/$",
            "delete_category",
            "category",
        ),
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self._compiled_patterns = [
            (re.compile(pattern), action, target_type)
            for pattern, action, target_type in self.PATTERNS
        ]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        # Only process for authenticated staff/admin accounts
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return response

        # Only log successful responses (redirects or 2xx)
        if not (200 <= response.status_code < 400):
            return response

        # Check if already logged explicitly by a service
        if getattr(request, "_audit_logged", False):
            return response

        path = request.path_info
        method = request.method.upper()

        action = None
        target_type = ""
        target_id = ""

        # Match specific patterns
        for regex, act, tgt in self._compiled_patterns:
            match = regex.match(path)
            if match:
                # View-only routes should only be logged on GET/HEAD
                if act.startswith(("view_", "download_")):
                    if method in ("GET", "HEAD"):
                        action = act
                        target_type = tgt
                        target_id = match.groupdict().get("id", "")
                        break
                elif method in ("POST", "PUT", "PATCH", "DELETE"):
                    action = act
                    target_type = tgt
                    target_id = match.groupdict().get("id", "")
                    break

        # Fallback: Catch any mutating action on admin/portal routes
        if (
            not action
            and method in ("POST", "PUT", "PATCH", "DELETE")
            and path.startswith(("/portal/", "/api/v1/admin/", "/admin/"))
        ):
            action = f"{method.lower()}_action"
            target_type = "admin_route"
            target_id = path

        if action:
            try:
                document_id = None
                if target_type == "document" and target_id.isdigit():
                    document_id = int(target_id)

                AdminAccessLog.objects.create(
                    admin=user,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id),
                    details=f"{method} {path}",
                    document_id=document_id,
                    ip_address=get_client_ip(request),
                )
                request._audit_logged = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("AdminActionLoggingMiddleware error: %s", exc)

        return response
