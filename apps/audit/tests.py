from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import AdminAccessLog

User = get_user_model()


class AuditLogImmutabilityTests(TestCase):
    """CP-1106 / TC-116: Audit logs must be strictly read-only and immutable."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            email="admin-audit@pup.edu.ph",
            password="AdminPassword123!",
            full_name="Admin Audit",
        )
        self.log = AdminAccessLog.objects.create(
            admin=self.admin,
            action="suspend_user",
            target_type="user",
            target_id="10",
            details="POST /api/v1/admin/users/10/suspend/",
        )

    def test_cannot_modify_existing_audit_log_via_save(self) -> None:
        """Attempting to update an existing audit log row must raise PermissionDenied."""
        self.log.action = "tampered_action"
        with self.assertRaises(PermissionDenied):
            self.log.save()

    def test_cannot_delete_audit_log_via_delete(self) -> None:
        """Attempting to delete an audit log row must raise PermissionDenied."""
        with self.assertRaises(PermissionDenied):
            self.log.delete()

    def test_cannot_bulk_delete_audit_logs(self) -> None:
        """Attempting to bulk-delete audit logs must raise PermissionDenied."""
        with self.assertRaises(PermissionDenied):
            AdminAccessLog.objects.filter(pk=self.log.pk).delete()

    def test_cannot_bulk_update_audit_logs(self) -> None:
        """Attempting to bulk-update audit logs must raise PermissionDenied."""
        with self.assertRaises(PermissionDenied):
            AdminAccessLog.objects.filter(pk=self.log.pk).update(action="hacked")

    def test_django_admin_permissions(self) -> None:
        """Django admin must disable add, change, and delete operations."""
        model_admin = admin.site._registry[AdminAccessLog]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))


class AdminAuditLogEndpointTests(APITestCase):
    """CP-1106: Read-only API endpoints for viewing audit logs."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            email="admin-api@pup.edu.ph",
            password="AdminPassword123!",
            full_name="Admin API",
        )
        self.regular = User.objects.create_user(
            email="student@pup.edu.ph",
            password="StudentPassword123!",
            full_name="Student User",
        )
        self.log1 = AdminAccessLog.objects.create(
            admin=self.admin,
            action="suspend_user",
            target_type="user",
            target_id="5",
            details="POST /portal/users/5/suspend/",
        )
        self.log2 = AdminAccessLog.objects.create(
            admin=self.admin,
            action="remove_listing",
            target_type="listing",
            target_id="12",
            details="POST /portal/listings/12/remove/",
        )
        self.list_url = reverse("api-admin-audit-log-list")
        self.detail_url = reverse(
            "api-admin-audit-log-detail", kwargs={"pk": self.log1.pk}
        )

    def test_unauthenticated_request_rejected(self) -> None:
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_staff_user_rejected(self) -> None:
        self.client.force_authenticate(user=self.regular)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_list_audit_logs(self) -> None:
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        results = response.data["results"]
        actions = [r["action"] for r in results]
        self.assertIn("suspend_user", actions)
        self.assertIn("remove_listing", actions)

    def test_filter_by_action(self) -> None:
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?action=suspend_user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["action"], "suspend_user")

    def test_search_audit_logs(self) -> None:
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f"{self.list_url}?search=listing")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["target_type"], "listing")

    def test_get_audit_log_detail(self) -> None:
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.log1.pk)
        self.assertEqual(response.data["action"], "suspend_user")
        self.assertEqual(response.data["admin_email"], self.admin.email)

    def test_modifying_methods_forbidden(self) -> None:
        """TC-116: PUT, PATCH, DELETE are rejected with 405 Method Not Allowed."""
        self.client.force_authenticate(user=self.admin)

        put_res = self.client.put(self.detail_url, {"action": "modified"})
        self.assertEqual(put_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        patch_res = self.client.patch(self.detail_url, {"action": "modified"})
        self.assertEqual(patch_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        del_res = self.client.delete(self.detail_url)
        self.assertEqual(del_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class AdminActionLoggingMiddlewareTests(TestCase):
    """CP-1106 / TC-115: Verifies middleware records audit logs for admin actions."""

    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            email="middleware-admin@pup.edu.ph",
            password="AdminPassword123!",
            full_name="Middleware Admin",
        )
        self.regular = User.objects.create_user(
            email="regular-user@pup.edu.ph",
            password="RegularPassword123!",
            full_name="Regular User",
        )

    def test_admin_config_change_automatically_logged(self) -> None:
        """TC-115: Performing an admin action automatically logs to audit trail."""
        from apps.audit.models import AdminAccessLog

        self.client.force_login(self.admin)
        initial_count = AdminAccessLog.objects.count()

        # Update system parameter via portal
        self.client.post(
            reverse("portal-system-parameters"),
            {"borrowing_limit": "5"},
        )

        # Check an audit log was generated
        new_count = AdminAccessLog.objects.count()
        self.assertGreater(new_count, initial_count)
        last_log = AdminAccessLog.objects.first()
        self.assertEqual(last_log.admin, self.admin)
        self.assertEqual(last_log.target_type, "system_config")

    def test_non_staff_action_not_logged(self) -> None:
        """Non-staff actions do not pollute the admin audit log."""
        from apps.audit.models import AdminAccessLog

        self.client.force_login(self.regular)
        initial_count = AdminAccessLog.objects.count()

        self.client.get("/")
        self.assertEqual(AdminAccessLog.objects.count(), initial_count)
