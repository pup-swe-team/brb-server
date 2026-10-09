from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser

from apps.listings.permissions import IsOwnerOrReadOnly
from apps.listings.tests.base import BaseListingTestCase


class IsOwnerOrReadOnlyPermissionTests(BaseListingTestCase):
    """Unit tests for the IsOwnerOrReadOnly permission class."""

    def setUp(self):
        super().setUp()
        self.permission = IsOwnerOrReadOnly()
        self.mock_view = Mock()

    def test_has_permission_authenticated_user(self):
        """Authenticated users have view-level permission for all methods."""
        request = Mock(user=self.owner)
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            request.method = method
            self.assertTrue(
                self.permission.has_permission(request, self.mock_view),
                f"Failed for method {method}",
            )

    def test_has_permission_anonymous_user(self):
        """Anonymous/Unauthenticated users are denied view-level permission."""
        request = Mock(user=AnonymousUser())
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            request.method = method
            self.assertFalse(
                self.permission.has_permission(request, self.mock_view),
                f"Failed for method {method}",
            )

    def test_has_object_permission_safe_methods(self):
        """Any user has object-level permission for safe methods."""
        for user in [self.owner, self.other_user, AnonymousUser()]:
            for method in ["GET", "HEAD", "OPTIONS"]:
                request = Mock(user=user, method=method)
                self.assertTrue(
                    self.permission.has_object_permission(
                        request, self.mock_view, self.listing
                    ),
                    f"Failed for user {user} and method {method}",
                )

    def test_has_object_permission_owner_unsafe_methods(self):
        """Owner has object-level permission for unsafe methods."""
        for method in ["PUT", "PATCH", "DELETE"]:
            request = Mock(user=self.owner, method=method)
            self.assertTrue(
                self.permission.has_object_permission(
                    request, self.mock_view, self.listing
                ),
                f"Failed for owner with method {method}",
            )

    def test_has_object_permission_non_owner_unsafe_methods(self):
        """Non-owner is denied object-level permission for unsafe methods."""
        for method in ["PUT", "PATCH", "DELETE"]:
            request = Mock(user=self.other_user, method=method)
            self.assertFalse(
                self.permission.has_object_permission(
                    request, self.mock_view, self.listing
                ),
                f"Failed for non-owner with method {method}",
            )
