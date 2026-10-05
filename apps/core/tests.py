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
