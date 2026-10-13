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
    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.account_status == User.AccountStatusChoices.ACTIVE
            and request.user.lender_status == User.LenderStatusChoices.ACTIVE
        )
