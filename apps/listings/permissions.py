from rest_framework import permissions

from apps.users.models import User


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.lender == request.user


class IsActiveLender(permissions.BasePermission):
    message = "Active lender status is required before you can post resources."
    code = "permission_denied"

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        if (
            getattr(user, "is_flag_confirmed", False)
            or getattr(user, "account_status", "") == "flagged"
            or getattr(user, "lender_status", "") == "flagged"
        ):
            self.message = (
                "Your account has been flagged. You are currently restricted from "
                "creating new listings. Please contact BRB support."
            )
            self.code = "account_flagged"
            return False
        return bool(
            user.account_status == User.AccountStatusChoices.ACTIVE
            and user.lender_status == User.LenderStatusChoices.ACTIVE
        )


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Allow authenticated users read-only access (GET, HEAD, OPTIONS).
    Require staff authority (is_staff=True) for write operations (POST, PUT, PATCH, DELETE).
    """

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user.is_staff)
