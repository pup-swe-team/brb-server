"""Tests for the CP-102 auto-deactivation job endpoint (SRS 2.4 / 5.2).

Lives in `apps.core` because that is where the endpoint is mounted
(`/api/v1/jobs/`), even though the work it performs belongs to `apps.users`.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import SystemConfig

User = get_user_model()

SECRET = "test-cron-secret-token"


def make_unverified_user(email: str, *, age_days: int) -> User:
    """A registered-but-never-confirmed account, backdated by `age_days`."""
    user = User.objects.create_user(
        email=email,
        password="StrongPassword123!",
        full_name="Test User",
        contact_number="09171234567",
        affiliation=User.AffiliationChoices.STUDENT,
    )
    user.account_status = User.AccountStatusChoices.PENDING_REVIEW
    user.created_at = timezone.now() - timedelta(days=age_days)
    user.save(update_fields=["created_at", "account_status"])
    return user


@override_settings(CRON_SECRET_TOKEN=SECRET)
class DeactivateUnverifiedAccountsViewTests(APITestCase):
    def setUp(self) -> None:
        self.url = reverse("job-deactivate-unverified")

    def run_job(self, header_value: str | None = None):
        headers = {} if header_value is None else {"HTTP_AUTHORIZATION": header_value}
        return self.client.post(self.url, **headers)

    # --- token enforcement (CONTRIBUTING.md 7.2 rule 6) ---

    def test_missing_authorization_header_is_rejected(self) -> None:
        """AC-102.S1: No secret -> 401 Unauthorized."""
        response = self.run_job(None)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_secret_is_rejected(self) -> None:
        """AC-102.S1: A wrong secret -> 401 Unauthorized."""
        response = self.run_job("Bearer not-the-secret")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_authorization_header_is_rejected(self) -> None:
        response = self.run_job("")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_bearer_prefixed_secret_is_accepted(self) -> None:
        """AC-102.S2: The correct secret runs the job."""
        response = self.run_job(f"Bearer {SECRET}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bare_secret_is_accepted(self) -> None:
        """cron-job.org can send the raw token; both header forms must work."""
        response = self.run_job(SECRET)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unset_secret_refuses_to_run(self) -> None:
        """A missing server-side secret must not degrade into allow-all."""
        with override_settings(CRON_SECRET_TOKEN=""):
            response = self.run_job(f"Bearer {SECRET}")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_get_is_not_allowed(self) -> None:
        """The job is triggered by POST only, so it cannot be a drive-by GET."""
        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {SECRET}")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # --- behaviour ---

    def test_removes_only_accounts_past_the_expiry_window(self) -> None:
        """AC-102.3: Unverified accounts older than 7 days are removed."""
        expired = make_unverified_user("expired@iskolarngbayan.pup.edu.ph", age_days=8)
        recent = make_unverified_user("recent@iskolarngbayan.pup.edu.ph", age_days=3)

        response = self.run_job(f"Bearer {SECRET}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deactivated_count"], 1)
        self.assertEqual(response.data["deactivated_user_ids"], [expired.pk])
        self.assertFalse(User.objects.filter(pk=expired.pk).exists())
        self.assertTrue(User.objects.filter(pk=recent.pk).exists())

    def test_leaves_verified_accounts_alone(self) -> None:
        """A confirmed account is never touched, however old it is."""
        verified = make_unverified_user(
            "verified@iskolarngbayan.pup.edu.ph", age_days=30
        )
        verified.email_verified_at = verified.created_at
        verified.account_status = User.AccountStatusChoices.ACTIVE
        verified.save(update_fields=["email_verified_at", "account_status"])

        response = self.run_job(f"Bearer {SECRET}")

        self.assertEqual(response.data["deactivated_count"], 0)
        self.assertTrue(User.objects.filter(pk=verified.pk).exists())

    def test_frees_the_email_for_re_registration(self) -> None:
        """
        AC-102.4: a removed account can be registered again from scratch.

        This is the check that deleting (rather than keeping a deactivated row)
        actually satisfies "require re-registration, no reactivation path" -- a
        retained row would still be holding the unique email address.
        """
        make_unverified_user("reuse@iskolarngbayan.pup.edu.ph", age_days=8)

        self.run_job(f"Bearer {SECRET}")

        payload = {
            "email": "reuse@iskolarngbayan.pup.edu.ph",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "full_name": "Reuse Test",
            "contact_number": "09171234567",
            "affiliation": "Student",
        }
        response = self.client.post(reverse("auth-register"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.filter(email=payload["email"]).count(), 1)

    def test_expiry_window_is_admin_configurable(self) -> None:
        """AC-102.3: the 7-day window reads from system_configs, not a constant."""
        user = make_unverified_user("config@iskolarngbayan.pup.edu.ph", age_days=2)

        SystemConfig.objects.create(
            config_key="email_verification_expiry_days", config_value="30"
        )
        response = self.run_job(f"Bearer {SECRET}")
        self.assertEqual(response.data["deactivated_count"], 0)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())

        SystemConfig.objects.filter(config_key="email_verification_expiry_days").update(
            config_value="1"
        )
        response = self.run_job(f"Bearer {SECRET}")
        self.assertEqual(response.data["deactivated_count"], 1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_malformed_config_value_falls_back_to_the_default(self) -> None:
        """A typo in an Admin-entered config must not take the job down."""
        SystemConfig.objects.create(
            config_key="email_verification_expiry_days", config_value="soon"
        )
        expired = make_unverified_user("typo@iskolarngbayan.pup.edu.ph", age_days=8)

        response = self.run_job(f"Bearer {SECRET}")

        self.assertEqual(response.data["expiry_days"], 7)
        self.assertEqual(response.data["deactivated_count"], 1)
        self.assertFalse(User.objects.filter(pk=expired.pk).exists())

    def test_response_reports_nothing_to_do(self) -> None:
        """The job is idempotent -- safe for cron-job.org to call repeatedly."""
        first = self.run_job(f"Bearer {SECRET}")
        second = self.run_job(f"Bearer {SECRET}")

        self.assertEqual(first.data["deactivated_count"], 0)
        self.assertEqual(second.data["deactivated_count"], 0)
        self.assertEqual(second.status_code, status.HTTP_200_OK)


class SystemConfigAdminTests(APITestCase):
    """
    CP-103 requires the lockout window to be *Admin-configurable*.

    That is only true if the model is actually reachable from the admin site. A
    ``SystemConfig`` row editable solely from ``manage.py shell`` would satisfy the
    letter of the ticket while failing its intent.
    """

    def test_system_config_is_reachable_and_editable(self) -> None:
        from django.contrib import admin

        from apps.core.models import SystemConfig

        self.assertIn(SystemConfig, admin.site._registry)
        model_admin = admin.site._registry[SystemConfig]
        # Key and value must both be browsable, or an Admin cannot find or change
        # a setting without knowing the schema.
        self.assertIn("config_key", model_admin.list_display)
        self.assertIn("config_value", model_admin.list_display)
        # Timestamps are audit information; they must not be editable.
        self.assertIn("created_at", model_admin.readonly_fields)
        self.assertIn("updated_at", model_admin.readonly_fields)

    def test_every_read_key_is_documented_in_the_admin_docstring(self) -> None:
        """
        `apps.core.selectors` falls back to a default when a key is absent, so a
        typo degrades silently instead of raising. The admin docstring is the only
        place an Admin can learn which keys exist, so every key the code reads has
        to be named there.
        """
        from django.contrib import admin as contrib_admin

        from apps.core.selectors import get_config

        self.assertIsNotNone(contrib_admin.site._registry[SystemConfig].__doc__)

        registered_doc = contrib_admin.site._registry[SystemConfig].__doc__ or ""
        for config_key in (
            "login_lockout_threshold",
            "login_lockout_minutes",
            "email_verification_expiry_days",
        ):
            self.assertIn(config_key, registered_doc)
            # And a missing row still yields a usable value rather than an error.
            self.assertIsNotNone(get_config(config_key, "fallback"))


class HealthzEndpointTests(APITestCase):
    """Render health checks hit `/healthz/` (D-23); it must answer 200."""

    def test_healthz_returns_ok_without_authentication(self) -> None:
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"status": "ok"})


class AdminSystemConfigEndpointTests(APITestCase):
    """CP-1104 / TC-111 / TC-112: System parameters configuration tests."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            email="admin@pup.edu.ph",
            password="AdminPassword123!",
            full_name="Admin Officer",
        )
        self.regular_user = User.objects.create_user(
            email="borrower@pup.edu.ph",
            password="BorrowerPass123!",
            full_name="Regular Borrower",
        )
        self.list_url = reverse("api-admin-config-list")
        self.detail_url = reverse(
            "api-admin-config-detail", kwargs={"key": "borrowing_limit"}
        )

    def test_unauthenticated_request_rejected(self) -> None:
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_staff_user_rejected(self) -> None:
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_list_all_configs(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        configs = response.data.get("configs", [])
        keys = [c["config_key"] for c in configs]
        self.assertIn("borrowing_limit", keys)
        self.assertIn("lending_limit", keys)
        self.assertIn("request_expiry_hours", keys)
        self.assertIn("auth_code_expiry_hours", keys)
        self.assertIn("review_window_days", keys)

    def test_admin_can_filter_by_category(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            f"{self.list_url}?category=Borrowing%20%26%20Lending"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        configs = response.data.get("configs", [])
        for c in configs:
            self.assertEqual(c["category"], "Borrowing & Lending")

    def test_admin_can_retrieve_single_config(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["config_key"], "borrowing_limit")
        self.assertEqual(response.data["default_value"], "3")

    def test_admin_can_update_single_config_and_takes_effect_immediately(self) -> None:
        """TC-111: Admin updates borrowing limit and it applies without redeployment."""
        from apps.core.constants import BORROWING_LIMIT
        from apps.core.selectors import get_int_config

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(self.detail_url, {"value": "5"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["config_value"], "5")

        # Verify database persisted updated_by and new value
        row = SystemConfig.objects.get(config_key=BORROWING_LIMIT)
        self.assertEqual(row.config_value, "5")
        self.assertEqual(row.updated_by, self.admin_user)

        # Verify selector reads the new value immediately (no redeploy needed)
        self.assertEqual(get_int_config(BORROWING_LIMIT, 3), 5)

    def test_admin_updates_code_expiry_duration(self) -> None:
        """TC-112: Admin updates code expiry duration."""
        from apps.core.constants import AUTH_CODE_EXPIRY_HOURS
        from apps.core.selectors import get_int_config

        url = reverse(
            "api-admin-config-detail", kwargs={"key": "auth_code_expiry_hours"}
        )
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.put(url, {"value": "2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["config_value"], "2")
        self.assertEqual(get_int_config(AUTH_CODE_EXPIRY_HOURS, 3), 2)

    def test_invalid_integer_rejected(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.patch(self.detail_url, {"value": "not-a-number"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_out_of_bounds_integer_rejected(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        # min for borrowing_limit is 1, max is 50
        response = self.client.patch(self.detail_url, {"value": "0"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response2 = self.client.patch(self.detail_url, {"value": "999"})
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_update_configs(self) -> None:
        self.client.force_authenticate(user=self.admin_user)
        payload = {
            "configs": {
                "borrowing_limit": "7",
                "lending_limit": "20",
                "review_window_days": "14",
            }
        }
        response = self.client.put(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            SystemConfig.objects.get(config_key="borrowing_limit").config_value, "7"
        )
        self.assertEqual(
            SystemConfig.objects.get(config_key="lending_limit").config_value, "20"
        )
        self.assertEqual(
            SystemConfig.objects.get(config_key="review_window_days").config_value, "14"
        )
