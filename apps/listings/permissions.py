from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        return (
            request.method in permissions.SAFE_METHODS and request.user.is_authenticated
        )

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.lender == request.user
