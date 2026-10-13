from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser

from apps.listings.permissions import IsActiveLender, IsOwnerOrReadOnly
from apps.listings.tests.base import BaseListingTestCase
from apps.users.models import User


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


class IsActiveLenderPermissionTests(BaseListingTestCase):
    """Unit tests for the IsActiveLender permission class."""

    def setUp(self):
        super().setUp()
        self.permission = IsActiveLender()
        self.mock_view = Mock()

    def test_has_permission_active_lender(self):
        """Active user with active lender status is granted permission."""
        request = Mock(user=self.owner)
        self.assertTrue(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_anonymous_user(self):
        """Anonymous user is denied permission safely without raising AttributeError."""
        request = Mock(user=AnonymousUser())
        self.assertFalse(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_unauthenticated_user(self):
        """Unauthenticated user object is denied permission."""
        user = Mock(
            is_authenticated=False,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        request = Mock(user=user)
        self.assertFalse(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_none_user(self):
        """Request with None user is denied permission safely."""
        request = Mock(user=None)
        self.assertFalse(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_non_lender_user(self):
        """Authenticated user with lender_status 'none' is denied permission."""
        request = Mock(user=self.other_user)
        self.assertFalse(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_revoked_lender(self):
        """Authenticated user with revoked lender status is denied permission."""
        user = User.objects.create_user(
            email="revoked_lender@iskolarngbayan.pup.edu.ph",
            password="password123",
            full_name="Revoked Lender",
            contact_number="09111111111",
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.REVOKED,
        )
        request = Mock(user=user)
        self.assertFalse(self.permission.has_permission(request, self.mock_view))

    def test_has_permission_inactive_account_statuses(self):
        """User with active lender status but inactive account status is denied permission."""
        inactive_statuses = [
            User.AccountStatusChoices.SUSPENDED,
            User.AccountStatusChoices.PENDING_REVIEW,
            User.AccountStatusChoices.BANNED,
            User.AccountStatusChoices.DEACTIVATED,
        ]
        for status in inactive_statuses:
            user = User.objects.create_user(
                email=f"user_{status}@iskolarngbayan.pup.edu.ph",
                password="password123",
                full_name=f"User {status}",
                contact_number="09222222222",
                account_status=status,
                lender_status=User.LenderStatusChoices.ACTIVE,
            )
            request = Mock(user=user)
            self.assertFalse(
                self.permission.has_permission(request, self.mock_view),
                f"Failed: User with account_status={status} should be denied",
            )
