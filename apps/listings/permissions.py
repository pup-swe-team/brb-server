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
