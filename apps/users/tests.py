from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs

from cryptography.fernet import Fernet, InvalidToken
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.test import APITestCase

from apps.audit.models import AdminAccessLog
from apps.core.models import SystemConfig

from .encryption import decrypt_document_data, encrypt_document_data
from .models import IdentityDocument, IdentityDocumentStatus, IdentityDocumentType
from .permissions import IsIdentityVerified
from .serializers import IdentityDocumentSubmissionSerializer
from .services import build_email_verification_token, email_verification_token_generator
from .tokens import EmailVerificationTokenGenerator

User = get_user_model()


class UserRegistrationTests(APITestCase):
    """
    Test suite for CP-101: Register with PUP-affiliated email.
    Covers server-side domain validation, domain-affiliation enforcement,
    pending/unverified account state, required fields, and response representation.
    """

    def setUp(self) -> None:
        self.register_url = reverse("auth-register")
        self.valid_student_payload = {
            "email": "juan.delacruz@iskolarngbayan.pup.edu.ph",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "full_name": "Juan Dela Cruz",
            "contact_number": "09171234567",
            "affiliation": "Student",
        }

    def test_register_student_success(self) -> None:
        """AC-1.1: Valid student registration creates account in pending_review state."""
        response = self.client.post(
            self.register_url, self.valid_student_payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["message"],
            "Registration successful. Check your email to verify your account "
            "before logging in.",
        )
        self.assertIn("user", response.data)
        user_data = response.data["user"]
        self.assertEqual(user_data["email"], "juan.delacruz@iskolarngbayan.pup.edu.ph")
        self.assertEqual(user_data["full_name"], "Juan Dela Cruz")
        self.assertEqual(user_data["contact_number"], "09171234567")
        self.assertEqual(user_data["affiliation"], "Student")
        self.assertEqual(user_data["account_status"], "pending_review")
        self.assertIsNone(user_data["email_verified_at"])
        self.assertNotIn("password", user_data)

        # Database record verification
        user = User.objects.get(email="juan.delacruz@iskolarngbayan.pup.edu.ph")
        self.assertTrue(user.check_password("StrongPassword123!"))
        self.assertEqual(user.account_status, User.AccountStatusChoices.PENDING_REVIEW)
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(user.affiliation, User.AffiliationChoices.STUDENT)

    def test_register_faculty_success(self) -> None:
        """AC-1.2: Valid faculty registration with @pup.edu.ph domain."""
        payload = {
            "email": "maria.santos@pup.edu.ph",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "full_name": "Prof. Maria Santos",
            "contact_number": "+639181234567",
            "affiliation": "Faculty",
        }
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["affiliation"], "Faculty")
        self.assertEqual(response.data["user"]["account_status"], "pending_review")

        user = User.objects.get(email="maria.santos@pup.edu.ph")
        self.assertEqual(user.affiliation, User.AffiliationChoices.FACULTY)
        self.assertEqual(user.account_status, User.AccountStatusChoices.PENDING_REVIEW)

    def test_register_staff_success(self) -> None:
        """AC-1.3: Valid staff registration with @pup.edu.ph domain."""
        payload = {
            "email": "pedro.penduko@pup.edu.ph",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
            "full_name": "Pedro Penduko",
            "contact_number": "09191234567",
            "affiliation": "Staff",
        }
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["affiliation"], "Staff")
        self.assertEqual(response.data["user"]["account_status"], "pending_review")

    def test_reject_non_pup_email_domain(self) -> None:
        """AC-1.4: Reject registration when email is not from an approved PUP domain."""
        invalid_emails = [
            "user@gmail.com",
            "user@yahoo.com",
            "user@outlook.com",
            "user@up.edu.ph",
            "user@pup.com",
        ]
        for email in invalid_emails:
            payload = self.valid_student_payload.copy()
            payload["email"] = email
            response = self.client.post(self.register_url, payload, format="json")
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Expected 400 for email {email}",
            )
            self.assertIn("email", response.data)

    def test_reject_student_with_faculty_domain(self) -> None:
        """AC-1.5: Enforce Student cannot use @pup.edu.ph domain."""
        payload = self.valid_student_payload.copy()
        payload["email"] = "student@pup.edu.ph"
        payload["affiliation"] = "Student"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("affiliation", response.data)

    def test_reject_faculty_with_student_domain(self) -> None:
        """AC-1.5: Enforce Faculty cannot use @iskolarngbayan.pup.edu.ph domain."""
        payload = self.valid_student_payload.copy()
        payload["email"] = "faculty@iskolarngbayan.pup.edu.ph"
        payload["affiliation"] = "Faculty"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("affiliation", response.data)

    def test_reject_staff_with_student_domain(self) -> None:
        """AC-1.5: Enforce Staff cannot use @iskolarngbayan.pup.edu.ph domain."""
        payload = self.valid_student_payload.copy()
        payload["email"] = "staff@iskolarngbayan.pup.edu.ph"
        payload["affiliation"] = "Staff"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("affiliation", response.data)

    def test_reject_admin_self_registration(self) -> None:
        """AC-1.6: Public self-registration as Admin is prohibited."""
        payload = self.valid_student_payload.copy()
        payload["email"] = "admin@pup.edu.ph"
        payload["affiliation"] = "Admin"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("affiliation", response.data)

    def test_reject_duplicate_email_registration(self) -> None:
        """AC-1.7: Re-registration of an already registered email is rejected."""
        self.client.post(self.register_url, self.valid_student_payload, format="json")

        # Attempt to register again with same email (even with case difference)
        duplicate_payload = self.valid_student_payload.copy()
        duplicate_payload["email"] = "JUAN.DELACRUZ@iskolarngbayan.pup.edu.ph"

        response = self.client.post(self.register_url, duplicate_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_required_fields_validation(self) -> None:
        """AC-1.8: Missing any required field fails with 400 Bad Request."""
        required_fields = [
            "email",
            "password",
            "password_confirm",
            "full_name",
            "contact_number",
            "affiliation",
        ]
        for field in required_fields:
            payload = self.valid_student_payload.copy()
            del payload[field]
            response = self.client.post(self.register_url, payload, format="json")
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Field {field} should be required",
            )
            self.assertIn(field, response.data)

    def test_reject_password_mismatch(self) -> None:
        """AC-1.9: Passwords that do not match are rejected."""
        payload = self.valid_student_payload.copy()
        payload["password_confirm"] = "DifferentPassword123!"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", response.data)

    def test_reject_weak_password(self) -> None:
        """AC-1.10: Weak passwords failing Django password validators are rejected."""
        payload = self.valid_student_payload.copy()
        payload["password"] = "123"
        payload["password_confirm"] = "123"

        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_reject_invalid_contact_number(self) -> None:
        """AC-1.11: Non-Philippine or malformed contact numbers are rejected."""
        invalid_numbers = [
            "12345",
            "0912345",
            "08123456789",  # Doesn't start with 09
            "+12345678901",
            "phone-number",
            "091234567890",  # 12 digits
        ]
        for number in invalid_numbers:
            payload = self.valid_student_payload.copy()
            payload["contact_number"] = number
            response = self.client.post(self.register_url, payload, format="json")
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Number {number} should be rejected",
            )
            self.assertIn("contact_number", response.data)

    def test_accept_plus63_contact_number_format(self) -> None:
        """AC-1.11: Contact number with +639 format is accepted."""
        payload = self.valid_student_payload.copy()
        payload["contact_number"] = "+639171234567"
        response = self.client.post(self.register_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["contact_number"], "+639171234567")

    def test_affiliation_does_not_gate_borrower_lender_defaults(self) -> None:
        """AC-1.13: Affiliation does not gate Borrower/Lender function."""
        # Both student and faculty have lender_status 'none' and can borrow/lend equally
        response = self.client.post(
            self.register_url, self.valid_student_payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["lender_status"], "none")


# ---------------------------------------------------------------------------
# Shared helpers for CP-102 / CP-103 / CP-105
# ---------------------------------------------------------------------------

STUDENT_PAYLOAD = {
    "email": "newcomer@iskolarngbayan.pup.edu.ph",
    "password": "StrongPassword123!",
    "password_confirm": "StrongPassword123!",
    "full_name": "Juan Dela Cruz",
    "contact_number": "09171234567",
    "affiliation": "Student",
}


def make_user(
    email: str = "juan.delacruz@iskolarngbayan.pup.edu.ph",
    *,
    password: str = "StrongPassword123!",
    full_name: str = "Juan Dela Cruz",
    affiliation: str | None = None,
    verified: bool = True,
    account_status: str | None = None,
    age_days: int = 0,
    is_staff: bool = False,
    contact_number: str = "09171234567",
) -> User:
    """
    Create a user directly, bypassing the registration endpoint.

    Tests for login and document submission need accounts in states that
    registration deliberately cannot produce (suspended, expired, already
    verified), so they build the row rather than driving three HTTP calls.
    """
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        contact_number=contact_number,
        affiliation=affiliation or User.AffiliationChoices.STUDENT,
    )

    if verified:
        user.email_verified_at = timezone.now()
        user.account_status = User.AccountStatusChoices.ACTIVE
    else:
        user.email_verified_at = None
        user.account_status = User.AccountStatusChoices.PENDING_REVIEW

    if account_status is not None:
        user.account_status = account_status

    if is_staff:
        user.is_staff = True

    if age_days:
        # created_at is auto_now_add, so it has to be written after the insert.
        User.objects.filter(pk=user.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        user.refresh_from_db()

    user.save()
    return user


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def png_upload(
    name: str = "pup_id.png", content_type: str = "image/png"
) -> SimpleUploadedFile:
    """A tiny valid PNG, so tests exercise real multipart handling."""
    return SimpleUploadedFile(name, PNG_BYTES, content_type=content_type)


# CP-105 document bytes go straight into the Postgres row, so identity tests never
# touch a storage backend at all. This override remains only so that any *other*
# file field a test happens to touch (e.g. `users.photo`) cannot write to the real
# filesystem or a third-party network service.
in_memory_storage = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


# ---------------------------------------------------------------------------
# CP-102 — Verify email address
# ---------------------------------------------------------------------------


class EmailVerificationTests(APITestCase):
    """CP-102: send a confirmation link, and honour it when clicked."""

    def setUp(self) -> None:
        self.register_url = reverse("auth-register")
        self.verify_url = reverse("auth-verify-email")
        self.user = make_user("unconfirmed@iskolarngbayan.pup.edu.ph", verified=False)

    def confirmation_payload(self, user: User | None = None) -> dict[str, str]:
        target = user or self.user
        return {
            "uid": self.uid_for(target),
            "token": build_email_verification_token(target),
        }

    @staticmethod
    def uid_for(user: User) -> str:
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        return urlsafe_base64_encode(force_bytes(user.pk))

    # --- sending ---

    def test_registration_sends_verification_email(self) -> None:
        """AC-102.1: A successful registration emails a confirmation link."""
        self.client.post(self.register_url, STUDENT_PAYLOAD, format="json")

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [STUDENT_PAYLOAD["email"]])

        user = User.objects.get(email=STUDENT_PAYLOAD["email"])
        self.assertIn(self.uid_for(user), message.body)

        # Validate the token that was actually mailed rather than comparing it to a
        # freshly minted one: the generator embeds a per-second timestamp, so a second
        # call can legitimately differ from the one sent during the request.
        link = message.body.split("?", 1)[1].split()[0]
        query = parse_qs(link)
        self.assertTrue(
            email_verification_token_generator().check_token(user, query["token"][0]),
            "The emailed token must validate for the newly registered user",
        )

    def test_registration_still_succeeds_when_email_sending_fails(self) -> None:
        """
        A mail outage must not strand the caller.

        The account already exists, so failing the request with a 5xx would only
        invite a retry that fails differently (duplicate email). The 7-day
        cleanup job is the real safety net.
        """
        with mock.patch(
            "apps.users.views.send_email_verification", side_effect=OSError("smtp down")
        ):
            response = self.client.post(
                self.register_url, STUDENT_PAYLOAD, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email=STUDENT_PAYLOAD["email"]).exists())

    def test_rejected_registration_sends_no_email(self) -> None:
        """A rejected registration must not produce a confirmation email."""
        payload = {**STUDENT_PAYLOAD, "email": "someone@gmail.com"}
        response = self.client.post(self.register_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    # --- confirming ---

    def test_valid_link_verifies_account_and_grants_access(self) -> None:
        """AC-102.2: Clicking the link marks the email verified and account active."""
        response = self.client.post(
            self.verify_url, self.confirmation_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertEqual(self.user.account_status, User.AccountStatusChoices.ACTIVE)
        self.assertEqual(response.data["user"]["account_status"], "active")
        self.assertIsNotNone(response.data["user"]["email_verified_at"])

    def test_verification_is_idempotent(self) -> None:
        """A double-tap on the link (or a second link) must not error out."""
        first = self.client.post(
            self.verify_url, self.confirmation_payload(), format="json"
        )
        second = self.client.post(
            self.verify_url, self.confirmation_payload(), format="json"
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_status, User.AccountStatusChoices.ACTIVE)

    def test_forged_token_is_rejected(self) -> None:
        """AC-102.2: A token that was not signed by this server is refused."""
        payload = {"uid": self.uid_for(self.user), "token": "abcdef-123456"}
        response = self.client.post(self.verify_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.email_verified_at)

    def test_token_issued_for_another_user_is_rejected(self) -> None:
        """A token is bound to the user it was minted for."""
        other = make_user("other@iskolarngbayan.pup.edu.ph", verified=False)
        payload = {
            "uid": self.uid_for(self.user),
            "token": build_email_verification_token(other),
        }

        response = self.client.post(self.verify_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.email_verified_at)

    def test_unknown_uid_is_rejected(self) -> None:
        """An unparseable or unknown uid fails without leaking that fact."""
        from django.utils.http import urlsafe_base64_encode

        payload = {
            "uid": urlsafe_base64_encode(b"99999999"),
            "token": build_email_verification_token(self.user),
        }
        response = self.client.post(self.verify_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_expired_token_is_rejected(self) -> None:
        """The link must not outlive its configured window."""
        token = build_email_verification_token(self.user)
        payload = {"uid": self.uid_for(self.user), "token": token}

        with mock.patch(
            "apps.users.serializers.email_verification_token_generator",
            return_value=EmailVerificationTokenGenerator(max_age_seconds=-1),
        ):
            response = self.client.post(self.verify_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.email_verified_at)

    def test_failures_are_indistinguishable(self) -> None:
        """
        Every failure mode returns the same message.

        Otherwise this public endpoint becomes a probe for which user ids exist
        and which of them have already confirmed their address.
        """
        messages = set()
        cases = [
            {"uid": "not-base64!!", "token": "abcdef-123456"},
            {"uid": self.uid_for(self.user), "token": "abcdef-123456"},
            {"uid": "OTk5OTk5OQ==", "token": "abcdef-123456"},
        ]
        for payload in cases:
            response = self.client.post(self.verify_url, payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            messages.add(str(response.data["detail"]))

        self.assertEqual(len(messages), 1)

    def test_verification_endpoint_requires_no_authentication(self) -> None:
        """The link is followed from an email client, so no token can be present."""
        response = self.client.post(
            self.verify_url, self.confirmation_payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_is_not_allowed(self) -> None:
        """
        Confirmation is POST-only.

        A GET endpoint would let any page, mail scanner or prefetcher silently
        verify an account just by loading a URL.
        """
        response = self.client.get(self.verify_url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class EmailVerificationTokenGeneratorTests(APITestCase):
    """
    The CP-102 token has its own lifetime, independent of PASSWORD_RESET_TIMEOUT.

    CP-104 needs reset links that expire in about an hour; CP-102 needs a
    week. If both rode the single global Django setting, changing one would
    silently change the other.
    """

    def test_token_lifetime_defaults_to_the_configured_expiry_window(self) -> None:
        from .services import email_verification_token_generator

        generator = email_verification_token_generator()
        self.assertEqual(generator.max_age_seconds, 7 * 24 * 60 * 60)

    def test_token_lifetime_follows_system_config(self) -> None:
        from .services import email_verification_token_generator

        SystemConfig.objects.create(
            config_key="email_verification_expiry_days", config_value="30"
        )
        self.assertEqual(
            email_verification_token_generator().max_age_seconds, 30 * 24 * 60 * 60
        )

    def test_valid_token_is_accepted_within_the_window(self) -> None:
        user = make_user(verified=False)
        generator = EmailVerificationTokenGenerator(max_age_seconds=3600)
        self.assertTrue(generator.check_token(user, generator.make_token(user)))

    def test_token_is_refused_outside_the_window(self) -> None:
        """
        A token older than the window must not verify anything.

        The lifetime is passed as -1 because the generator compares whole seconds:
        a zero-second window would still accept a token minted in the same second.
        """
        user = make_user("stale@iskolarngbayan.pup.edu.ph", verified=False)
        stale = EmailVerificationTokenGenerator(max_age_seconds=-1)
        fresh = EmailVerificationTokenGenerator(max_age_seconds=3600)

        self.assertFalse(stale.check_token(user, fresh.make_token(user)))

    def test_garbage_token_is_refused_without_raising(self) -> None:
        user = make_user(verified=False)
        generator = EmailVerificationTokenGenerator(max_age_seconds=3600)
        for bad in ["", "garbage", "!!!-123", "abc-def"]:
            self.assertFalse(generator.check_token(user, bad))

    def test_garbage_uid_does_not_crash_the_endpoint(self) -> None:
        """The uid is decoded from a URL, so it is attacker-controlled input."""
        user = make_user(verified=False)
        response = self.client.post(
            reverse("auth-verify-email"),
            {"uid": "%%%%", "token": build_email_verification_token(user)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# CP-103 — Log in to account
# ---------------------------------------------------------------------------


class LoginTests(APITestCase):
    """CP-103: authenticate credentials, and refuse everything that should be."""

    def setUp(self) -> None:
        self.login_url = reverse("auth-login")
        self.valid_payload = {
            "email": "juan.delacruz@iskolarngbayan.pup.edu.ph",
            "password": "StrongPassword123!",
        }
        self.user = make_user()

    def login(self, payload: dict | None = None):
        return self.client.post(
            self.login_url, payload or self.valid_payload, format="json"
        )

    def test_login_success_returns_tokens(self) -> None:
        """AC-103.1: Valid credentials are authenticated server-side."""
        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])
        self.assertEqual(response.data["user"]["email"], self.valid_payload["email"])

    def test_login_records_last_login(self) -> None:
        self.assertIsNone(self.user.last_login)
        self.login()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_issued_access_token_authenticates_a_request(self) -> None:
        """The pair is only useful if it actually passes JWTAuthentication."""
        access = self.login().data["tokens"]["access"]
        response = self.client.get(
            reverse("identity-document-list"), HTTP_AUTHORIZATION=f"Bearer {access}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_email_match_is_case_insensitive(self) -> None:
        payload = {
            **self.valid_payload,
            "email": "JUAN.DELACRUZ@iskolarngbayan.pup.edu.ph",
        }
        response = self.login(payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_wrong_password_is_rejected(self) -> None:
        """AC-103.2: Bad credentials get the generic error."""
        response = self.login({**self.valid_payload, "password": "WrongPassword123!"})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Invalid email or password.")

    def test_unknown_email_returns_the_identical_generic_error(self) -> None:
        """
        AC-103.2: no email/password hint.

        This is the assertion that stops the login endpoint from confirming which
        addresses are registered -- the message must be byte-identical to the
        wrong-password case.
        """
        wrong_password = self.login(
            {**self.valid_payload, "password": "WrongPassword123!"}
        )
        unknown_email = self.login({**self.valid_payload, "email": "nobody@pup.edu.ph"})

        self.assertEqual(wrong_password.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(unknown_email.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(wrong_password.data["detail"], unknown_email.data["detail"])
        self.assertNotIn("nobody@pup.edu.ph", str(unknown_email.data))

    def test_missing_fields_are_rejected(self) -> None:
        for field in ("email", "password"):
            payload = self.valid_payload.copy()
            del payload[field]
            response = self.login(payload)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unverified_email_cannot_log_in(self) -> None:
        """
        AC-102.2 + CP-103: verification is what grants full access.

        Note this needs the *correct* password: the refusal is deliberately not
        reachable by someone who does not already know the password.
        """
        user = make_user("unverified@iskolarngbayan.pup.edu.ph", verified=False)
        response = self.login(
            {
                "email": user.email,
                "password": "StrongPassword123!",
            }
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Confirm your email address", response.data["detail"])

    def test_suspended_account_cannot_log_in(self) -> None:
        """AC-103.4: Suspended accounts are denied."""
        user = make_user(
            "suspended@iskolarngbayan.pup.edu.ph",
            account_status=User.AccountStatusChoices.SUSPENDED,
        )
        response = self.login({"email": user.email, "password": "StrongPassword123!"})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("suspended", response.data["detail"])

    def test_banned_account_cannot_log_in(self) -> None:
        """AC-103.4: Banned accounts are denied."""
        user = make_user(
            "banned@iskolarngbayan.pup.edu.ph",
            account_status=User.AccountStatusChoices.BANNED,
        )
        response = self.login({"email": user.email, "password": "StrongPassword123!"})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("banned", response.data["detail"])

    def test_account_status_refusal_is_not_reachable_without_the_password(self) -> None:
        """
        The suspension message is only shown to someone who already knows the
        password, so it cannot be used to enumerate account state.
        """
        user = make_user(
            "suspended2@iskolarngbayan.pup.edu.ph",
            account_status=User.AccountStatusChoices.SUSPENDED,
        )
        response = self.login({"email": user.email, "password": "Guessing123456!"})

        self.assertEqual(response.data["detail"], "Invalid email or password.")


class LoginLockoutTests(APITestCase):
    """AC-103.3: 5 consecutive failures lock the account for 15 minutes."""

    def setUp(self) -> None:
        self.login_url = reverse("auth-login")
        self.user = make_user("locked@iskolarngbayan.pup.edu.ph")
        self.bad_payload = {
            "email": self.user.email,
            "password": "WrongPassword123!",
        }
        self.good_payload = {
            "email": self.user.email,
            "password": "StrongPassword123!",
        }

    def fail_login(self):
        return self.client.post(self.login_url, self.bad_payload, format="json")

    def succeed_login(self):
        return self.client.post(self.login_url, self.good_payload, format="json")

    def test_fifth_failure_locks_the_account(self) -> None:
        """AC-103.3: The 5th consecutive failure starts a 15-minute lockout."""
        for attempt in range(1, 5):
            self.fail_login()
            self.user.refresh_from_db()
            self.assertEqual(
                self.user.failed_login_attempts,
                attempt,
                f"Attempt {attempt} should be counted",
            )

        self.assertIsNone(self.user.locked_until, "Not locked before the 5th failure")

        self.fail_login()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)
        self.assertTrue(self.user.is_locked_out)

    def test_correct_password_is_refused_while_locked_out(self) -> None:
        """The lockout holds even against the right password."""
        for _ in range(5):
            self.fail_login()

        response = self.succeed_login()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Too many failed login attempts", response.data["detail"])
        self.assertIn("15", response.data["detail"])

    def test_lockout_expires_after_the_configured_window(self) -> None:
        """After 15 minutes the account works again."""
        for _ in range(5):
            self.fail_login()

        self.user.refresh_from_db()
        User.objects.filter(pk=self.user.pk).update(
            locked_until=timezone.now() - timedelta(seconds=1)
        )

        response = self.succeed_login()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertFalse(self.user.is_locked_out)

    def test_counter_resets_after_the_lockout_expires(self) -> None:
        """An expired lock grants a fresh set of attempts, not a permanent ban."""
        for _ in range(5):
            self.fail_login()
        self.user.refresh_from_db()
        User.objects.filter(pk=self.user.pk).update(
            locked_until=timezone.now() - timedelta(seconds=1)
        )

        self.assertEqual(self.succeed_login().status_code, status.HTTP_200_OK)

        for _ in range(5):
            self.fail_login()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked_out, "A second lockout should be reachable")

    def test_successful_login_resets_the_failure_streak(self) -> None:
        """Failures must be *consecutive*: a success clears the count."""
        for _ in range(4):
            self.fail_login()

        self.assertEqual(self.succeed_login().status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)

        # A 5th failure after the reset must not lock.
        self.fail_login()
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        self.assertIsNone(self.user.locked_until)

    def test_threshold_is_admin_configurable(self) -> None:
        """The 5-attempt threshold reads from system_configs."""
        SystemConfig.objects.create(
            config_key="login_lockout_threshold", config_value="2"
        )

        self.fail_login()
        self.fail_login()

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked_out)

    def test_lockout_duration_is_admin_configurable(self) -> None:
        """The 15-minute duration reads from system_configs."""
        SystemConfig.objects.create(
            config_key="login_lockout_minutes", config_value="45"
        )

        for _ in range(5):
            self.fail_login()

        self.user.refresh_from_db()
        remaining = (self.user.locked_until - timezone.now()).total_seconds() / 60
        self.assertAlmostEqual(remaining, 45, delta=1)

    def test_lockout_message_reflects_a_custom_duration(self) -> None:
        SystemConfig.objects.create(
            config_key="login_lockout_minutes", config_value="45"
        )
        for _ in range(5):
            self.fail_login()

        response = self.succeed_login()
        self.assertIn("45", response.data["detail"])

    def test_malformed_config_falls_back_to_defaults(self) -> None:
        """A bad Admin value must not disable lockout entirely."""
        SystemConfig.objects.create(
            config_key="login_lockout_threshold", config_value="not-a-number"
        )

        for _ in range(4):
            self.fail_login()
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_locked_out)

        self.fail_login()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked_out)

    def test_counter_survives_repeated_failures_without_reset(self) -> None:
        """
        Each failure accumulates rather than overwriting.

        `_record_failed_attempt` uses an F() update so simultaneous attempts
        cannot lose each other's increment; this asserts the observable
        consequence without relying on real thread interleaving (SQLite in
        tests makes that unreliable).
        """
        for expected in (1, 2, 3, 4):
            self.fail_login()
            self.user.refresh_from_db()
            self.assertEqual(self.user.failed_login_attempts, expected)


class TokenLifecycleTests(APITestCase):
    """CP-103: refreshing, rotating, logging out, and losing an account."""

    def setUp(self) -> None:
        self.login_url = reverse("auth-login")
        self.refresh_url = reverse("auth-token-refresh")
        self.logout_url = reverse("auth-logout")
        self.user = make_user("tokens@iskolarngbayan.pup.edu.ph")
        tokens = self.login().data["tokens"]
        self.access = tokens["access"]
        self.refresh = tokens["refresh"]

    def login(self):
        return self.client.post(
            self.login_url,
            {"email": self.user.email, "password": "StrongPassword123!"},
            format="json",
        )

    def refresh_tokens(self, token: str | None = None):
        # `is None`, not `or`: an empty string is a test case, not a fallback.
        return self.client.post(
            self.refresh_url,
            {"refresh": self.refresh if token is None else token},
            format="json",
        )

    # --- refresh / rotation ---

    def test_refresh_returns_a_new_access_token(self) -> None:
        response = self.refresh_tokens()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_refresh_rotates_the_refresh_token(self) -> None:
        """ROTATE_REFRESH_TOKENS is on, so a new refresh token comes back."""
        response = self.refresh_tokens()

        self.assertIn("refresh", response.data)
        self.assertNotEqual(response.data["refresh"], self.refresh)

    def test_rotated_out_refresh_token_cannot_be_reused(self) -> None:
        """Blacklisting after rotation is what stops replay of an old token."""
        self.refresh_tokens()

        response = self.refresh_tokens(self.refresh)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_refresh_token_is_rejected(self) -> None:
        """Garbage that parses as a token attempt is refused, not crashed on."""
        for bad in ["not-a-token", "aaaa.bbbb"]:
            response = self.refresh_tokens(bad)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertIn("Invalid or expired refresh token.", response.data["detail"])

    def test_blank_refresh_token_is_a_validation_error(self) -> None:
        """A missing value is a 400 shape problem, distinct from a bad token."""
        response = self.refresh_tokens("")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("refresh", response.data)

    # --- logout ---

    def test_logout_blacklists_the_refresh_token(self) -> None:
        """AC-103.5: Logging out ends the session."""
        response = self.client.post(
            self.logout_url,
            {"refresh": self.refresh},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(
            self.refresh_tokens().status_code,
            status.HTTP_401_UNAUTHORIZED,
            "A blacklisted refresh token must not work again",
        )

    def test_logout_requires_authentication(self) -> None:
        response = self.client.post(
            self.logout_url, {"refresh": self.refresh}, format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_logout_with_a_bad_token_is_rejected(self) -> None:
        response = self.client.post(
            self.logout_url,
            {"refresh": "garbage"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- an account that disappears ---

    def test_access_token_stops_working_once_the_account_is_deleted(self) -> None:
        """
        CP-102 removes unverified accounts; their tokens must die with them.
        """
        self.user.delete()

        response = self.client.get(
            reverse("identity-document-list"),
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_refresh_for_a_deleted_account_is_401_not_500(self) -> None:
        """
        SimpleJWT's own TokenRefreshSerializer calls objects.get() without
        catching DoesNotExist, which turns a removed account into an unhandled
        500. RefreshSerializer exists specifically to avoid that.
        """
        self.user.delete()

        response = self.refresh_tokens()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("no longer active", response.data["detail"])

    def test_refresh_for_an_inactive_account_is_refused(self) -> None:
        """A token issued before deactivation must stop working once it happens.

        Tokens are minted while the account is still active because CP-103 also
        refuses logins for deactivated accounts; the point here is that an
        already-issued token does not outlive the `is_active` flag.
        """
        flagged = make_user("flagged@iskolarngbayan.pup.edu.ph")

        issued = self.client.post(
            self.login_url,
            {"email": flagged.email, "password": "StrongPassword123!"},
            format="json",
        )
        refresh = issued.data["tokens"]["refresh"]

        flagged.is_active = False
        flagged.save(update_fields=["is_active"])

        response = self.client.post(
            self.refresh_url, {"refresh": refresh}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("no longer active", response.data["detail"])


# ---------------------------------------------------------------------------
# CP-105 — Submit identity verification document
# ---------------------------------------------------------------------------


@in_memory_storage
class IdentityDocumentSubmissionTests(APITestCase):
    """CP-105: store the document, capture consent, guard the ID number."""

    def setUp(self) -> None:
        self.submit_url = reverse("identity-document-submit")
        self.user = make_user("submitter@iskolarngbayan.pup.edu.ph")
        self.client.force_authenticate(self.user)

    def submit(self, **overrides):
        payload = {
            "document_type": "pup_id",
            "id_number": "2024-00123",
            "name_on_document": "Juan Dela Cruz",
            "document_file": png_upload(),
            "consent_given": "true",
        }
        payload.update(overrides)
        return self.client.post(self.submit_url, payload, format="multipart")

    # --- storing ---

    def test_submission_is_stored_with_a_pending_status(self) -> None:
        """AC-105.1: The uploaded document and its submission record are stored."""
        response = self.submit()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["document_type"], "pup_id")
        self.assertEqual(response.data["id_number"], "2024-00123")

        document = IdentityDocument.objects.get(user=self.user)
        # The bytes are in the row itself, byte-for-byte as uploaded.
        self.assertEqual(bytes(document.document_data), PNG_BYTES)
        self.assertEqual(document.status.name, "pending")
        self.assertIsNotNone(document.submitted_at)

    def test_lookup_tables_are_seeded_by_migration(self) -> None:
        """CP-105 depends on these rows existing; the migration seeds them."""
        self.assertTrue(IdentityDocumentType.objects.filter(name="pup_id").exists())
        self.assertTrue(
            IdentityDocumentType.objects.filter(name="government_id").exists()
        )
        for name in ("pending", "approved", "rejected"):
            self.assertTrue(IdentityDocumentStatus.objects.filter(name=name).exists())

    def test_stored_file_is_not_exposed_in_the_response(self) -> None:
        """
        FR3: the document is Administrator-only.

        The response must never carry the document bytes -- not even to the
        person who uploaded them.
        """
        response = self.submit()

        self.assertNotIn("document_data", response.data)
        self.assertNotIn("identity_documents/", str(response.data))

    # --- consent ---

    def test_consent_is_required(self) -> None:
        """AC-105.4: Submission without explicit consent is refused."""
        response = self.submit(consent_given="false")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("consent_given", response.data)
        self.assertFalse(IdentityDocument.objects.exists())

    def test_consent_is_recorded_with_a_timestamp(self) -> None:
        """AC-105.4: Consent is captured alongside the submission."""
        self.submit()

        document = IdentityDocument.objects.get(user=self.user)
        self.assertTrue(document.consent_given)
        self.assertIsNotNone(document.consented_at)

    def test_consent_timestamp_cannot_diverge_from_the_consent_flag(self) -> None:
        """The DB constraint keeps `consent_given` and `consented_at` in step."""
        from django.db import IntegrityError, transaction

        document = IdentityDocument(
            user=self.user,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-99999",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
            consent_given=True,
            consented_at=None,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            document.save()

    # --- ID number uniqueness ---

    def test_id_number_already_linked_to_another_account_is_rejected(self) -> None:
        """AC-105.3: An ID number belongs to one account only."""
        other = make_user("other-owner@iskolarngbayan.pup.edu.ph")
        IdentityDocument.objects.create(
            user=other,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-00123",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )

        response = self.submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "already linked to another account", str(response.data["id_number"])
        )
        self.assertEqual(IdentityDocument.objects.filter(user=self.user).count(), 0)

    def test_id_number_comparison_is_case_insensitive(self) -> None:
        """IDs are retyped by hand, so case cannot make one 'different'."""
        other = make_user("case-owner@iskolarngbayan.pup.edu.ph")
        IdentityDocument.objects.create(
            user=other,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-ABC01",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )

        response = self.submit(id_number="2024-abc01")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already linked", str(response.data["id_number"]))

    def test_same_account_may_resubmit_the_same_id_number(self) -> None:
        """
        CP-106 allows resubmission after a rejection, so the same person
        re-sending the same ID must not collide with their own history.
        """
        self.assertEqual(self.submit().status_code, status.HTTP_201_CREATED)

        response = self.submit()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(IdentityDocument.objects.filter(user=self.user).count(), 2)

    def test_id_number_is_normalised_to_upper_case(self) -> None:
        response = self.submit(id_number=" 2024-lower ")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["id_number"], "2024-LOWER")

    # --- mismatch flagging ---

    def test_name_mismatch_is_flagged_but_still_accepted(self) -> None:
        """
        AC-105.2: A mismatch is flagged for Admin review, not used to reject.
        """
        response = self.submit(name_on_document="Juan Dela Cruze")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["has_profile_mismatch"])
        self.assertIn("closer look", response.data["message"])

        document = IdentityDocument.objects.get(user=self.user)
        self.assertTrue(document.has_profile_mismatch)

    def test_matching_name_is_not_flagged(self) -> None:
        response = self.submit()

        self.assertFalse(response.data["has_profile_mismatch"])

    def test_name_comparison_ignores_case_spacing_and_punctuation(self) -> None:
        """
        The same person's name is not a mismatch because a printed ID happens to
        use different spacing or a hyphen.
        """
        for variant in [
            "JUAN DELA CRUZ",
            "juan   dela  cruz",
            "Juan Dela-Cruz",
            "Juan  Dela Cruz.",
        ]:
            response = self.submit(name_on_document=variant, id_number="X-1")
            with self.subTest(variant=variant):
                self.assertFalse(
                    response.data["has_profile_mismatch"],
                    f"{variant!r} should not be treated as a mismatch",
                )

    # --- validation ---

    def test_unverified_email_cannot_submit(self) -> None:
        """
        Document submission is gated behind email confirmation.

        This is also what protects the CP-102 cleanup job: it deletes accounts
        that never confirmed, and `identity_documents.user` cascades, so an
        unconfirmed submission would be destroyed before an Admin ever saw it.
        """
        unverified = make_user("unverified@iskolarngbayan.pup.edu.ph", verified=False)
        self.client.force_authenticate(unverified)

        response = self.submit()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Confirm your email address", str(response.data))
        self.assertFalse(IdentityDocument.objects.exists())

    def test_unknown_document_type_is_rejected(self) -> None:
        response = self.submit(document_type="passport")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("document_type", response.data)

    def test_government_id_type_is_accepted(self) -> None:
        response = self.submit(document_type="government_id")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_disallowed_file_type_is_rejected(self) -> None:
        response = self.submit(
            document_file=SimpleUploadedFile(
                "malware.exe", b"MZ...", "application/x-msdownload"
            )
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("document_file", response.data)

    def test_oversized_file_is_rejected(self) -> None:
        from .constants import MAX_IDENTITY_DOCUMENT_BYTES

        oversized = SimpleUploadedFile(
            "big.png", b"0" * (MAX_IDENTITY_DOCUMENT_BYTES + 1), "image/png"
        )

        response = self.submit(document_file=oversized)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("5MB or smaller", str(response.data["document_file"]))

    def test_file_at_the_size_limit_is_accepted(self) -> None:
        """
        Boundary: exactly 5MB passes, one byte more does not (AC-105 upload cap).

        Exercised at the field level rather than over HTTP. Anything above Django's
        2.5MB FILE_UPLOAD_MAX_MEMORY_SIZE is spooled to an on-disk temporary file,
        which the Windows test runner cannot then re-read ("file is being used by
        another process"). The cap itself is storage-independent, so validating the
        uploaded file directly tests the real rule without that platform artifact.
        """
        from .constants import MAX_IDENTITY_DOCUMENT_BYTES

        field = IdentityDocumentSubmissionSerializer()

        at_limit = SimpleUploadedFile(
            "limit.png", b"0" * MAX_IDENTITY_DOCUMENT_BYTES, "image/png"
        )
        self.assertIs(field.validate_document_file(at_limit), at_limit)

        just_over = SimpleUploadedFile(
            "over.png", b"0" * (MAX_IDENTITY_DOCUMENT_BYTES + 1), "image/png"
        )
        with self.assertRaises(serializers.ValidationError) as caught:
            field.validate_document_file(just_over)
        self.assertIn("5MB or smaller", str(caught.exception.detail))

    def test_pdf_documents_are_accepted(self) -> None:
        response = self.submit(
            document_file=SimpleUploadedFile(
                "id.pdf", b"%PDF-1.4 fake", "application/pdf"
            )
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_missing_required_fields_are_rejected(self) -> None:
        for field in (
            "document_type",
            "id_number",
            "name_on_document",
            "document_file",
        ):
            payload = {
                "document_type": "pup_id",
                "id_number": "2024-00123",
                "name_on_document": "Juan Dela Cruz",
                "document_file": png_upload(),
                "consent_given": "true",
            }
            del payload[field]

            response = self.client.post(self.submit_url, payload, format="multipart")
            with self.subTest(field=field):
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submission_requires_authentication(self) -> None:
        self.client.force_authenticate(None)
        response = self.submit()
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_rejected_submission_stores_nothing(self) -> None:
        """No partial writes: a refused submission leaves no row behind."""
        self.submit(id_number="A", consent_given="false")
        self.submit(document_type="passport")

        self.assertEqual(IdentityDocument.objects.count(), 0)


@in_memory_storage
class IdentityDocumentListTests(APITestCase):
    """The submission history a client shows the user (CP-105)."""

    def setUp(self) -> None:
        self.list_url = reverse("identity-document-list")
        self.user = make_user("lister@iskolarngbayan.pup.edu.ph")

    def create_document(self, user: User, id_number: str) -> IdentityDocument:
        return IdentityDocument.objects.create(
            user=user,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number=id_number,
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
            consent_given=True,
            consented_at=timezone.now(),
        )

    def test_list_returns_only_the_callers_submissions(self) -> None:
        mine = self.create_document(self.user, "MINE-1")
        theirs = self.create_document(
            make_user("stranger@iskolarngbayan.pup.edu.ph"), "THEIRS-1"
        )

        self.client.force_authenticate(self.user)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], mine.pk)
        self.assertNotIn(theirs.pk, [row["id"] for row in response.data["results"]])

    def test_list_never_exposes_the_stored_file(self) -> None:
        """FR3 again: status is shareable, the document is not."""
        self.create_document(self.user, "MINE-2")

        self.client.force_authenticate(self.user)
        response = self.client.get(self.list_url)

        self.assertNotIn("document_data", response.data["results"][0])
        self.assertNotIn("identity_documents/", str(response.data))

    def test_list_requires_authentication(self) -> None:
        response = self.client.get(self.list_url)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class IdentityVerificationGateTests(APITestCase):
    """
    AC-105.5: listing creation and item requests stay blocked until verified.

    CP-401 and CP-501 have not been built, so there is no real endpoint to hang
    this on yet. The gate is therefore exercised directly against the permission
    class, which is what whoever wires it up in Sprint 2/3 will rely on.
    """

    def setUp(self) -> None:
        self.user = make_user("gated@iskolarngbayan.pup.edu.ph")

    def gate(self) -> IsIdentityVerified:
        return IsIdentityVerified()

    def granted(self, user: User) -> bool:
        return self.gate().has_permission(_request_for(user), None)

    def add_document(self, user: User, status_name: str, id_number: str) -> None:
        IdentityDocument.objects.create(
            user=user,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number=id_number,
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name=status_name),
            consent_given=True,
            consented_at=timezone.now(),
        )

    def test_unverified_user_is_denied(self) -> None:
        self.assertFalse(self.granted(self.user))

    def test_user_with_a_pending_document_is_still_denied(self) -> None:
        """Submission alone does not unlock anything; Admin approval does."""
        self.add_document(self.user, "pending", "PENDING-1")

        self.assertFalse(self.granted(self.user))

    def test_rejected_document_does_not_unlock(self) -> None:
        self.add_document(self.user, "rejected", "REJECTED-1")

        self.assertFalse(self.granted(self.user))

    def test_approved_document_unlocks_the_action(self) -> None:
        self.add_document(self.user, "approved", "APPROVED-1")

        self.assertTrue(self.granted(self.user))

    def test_email_verification_alone_does_not_unlock_the_action(self) -> None:
        """
        Confirming an email (CP-102) is not identity verification (CP-105).

        These are deliberately separate flags; conflating them would unlock
        listing creation for anyone who can click a link.
        """
        self.assertTrue(self.user.is_email_verified)
        self.assertFalse(self.user.has_verified_identity())

    def test_approval_on_a_different_account_does_not_unlock(self) -> None:
        self.add_document(
            make_user("somebody-else@iskolarngbayan.pup.edu.ph"), "approved", "OTHER-1"
        )

        self.assertFalse(self.granted(self.user))

    def test_unauthenticated_caller_is_denied(self) -> None:
        """DRF raises 401/403 from the auth class first; the gate must not pass."""
        anonymous_request = _request_for(User(pk=9999, is_active=True))
        anonymous_request.user = AnonymousUser()

        self.assertFalse(self.gate().has_permission(anonymous_request, None))


def _request_for(user: User):
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().post("/__test__/identity-gated/")
    request.user = user
    request._force_auth_user = True
    return request


class IdentityDocumentAdminTests(APITestCase):
    """
    FR3: the stored document is Administrator-only, and the admin is the one
    surface allowed to show it.

    Two things must hold: an Admin can find submissions at all (CP-106 depends on
    it), and the document bytes never appear in a list page.
    """

    def test_identity_document_is_registered_in_admin(self) -> None:
        from django.contrib import admin

        self.assertIn(IdentityDocument, admin.site._registry)

    def test_document_bytes_are_never_a_list_column(self) -> None:
        """
        A 5MB blob per row would make the changelist unusable, and it would also
        mean every Admin list view renders every unencrypted document at once.
        """
        from django.contrib import admin

        model_admin = admin.site._registry[IdentityDocument]
        self.assertNotIn("document_data", model_admin.list_display)
        self.assertNotIn("document_data", model_admin.list_filter)

    def test_admin_reports_document_size_without_exposing_content(self) -> None:
        user = make_user("admin-reviewer@iskolarngbayan.pup.edu.ph")
        document = IdentityDocument.objects.create(
            user=user,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-55555",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )

        from django.contrib import admin

        summary = admin.site._registry[IdentityDocument].document(document)

        self.assertEqual(summary, f"{len(PNG_BYTES):,} bytes")
        self.assertNotIn("PNG", summary)

    def test_submitted_fields_are_readonly_for_reviewers(self) -> None:
        """
        A reviewer decides *status*; they must not be able to rewrite the evidence
        they are judging, or swap the document out from under the decision.
        """
        from django.contrib import admin

        readonly = set(admin.site._registry[IdentityDocument].readonly_fields)
        for field in (
            "user",
            "document_type",
            "id_number",
            "download_link",
            "name_on_document",
        ):
            self.assertIn(field, readonly)


# ---------------------------------------------------------------------------
# CP-106 — Admin review of identity verification
# ---------------------------------------------------------------------------


class IdentityDocumentReviewTests(APITestCase):
    """
    Test suite for CP-106: Admin review of identity verification.
    Covers approve/reject transitions, rejection reason requirements,
    reviewer audit stamping, notifications (in-app & email), unlock of
    IsIdentityVerified gate, and resubmission allowance after rejection.
    """

    def setUp(self) -> None:
        self.submitter = make_user("submitter@iskolarngbayan.pup.edu.ph")
        self.admin = make_user(
            "admin@pup.edu.ph", affiliation=User.AffiliationChoices.FACULTY
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=["is_staff"])

        self.pending_status = IdentityDocumentStatus.objects.get(name="pending")
        self.approved_status = IdentityDocumentStatus.objects.get(name="approved")
        self.rejected_status = IdentityDocumentStatus.objects.get(name="rejected")
        self.doc_type = IdentityDocumentType.objects.get(name="pup_id")

        self.document = IdentityDocument.objects.create(
            user=self.submitter,
            document_type=self.doc_type,
            id_number="2024-00123",
            document_data=PNG_BYTES,
            status=self.pending_status,
            name_on_document="Juan Dela Cruz",
            consent_given=True,
            consented_at=timezone.now(),
        )
        self.review_url = reverse(
            "identity-document-review", kwargs={"pk": self.document.pk}
        )

    def review(self, payload: dict, as_user: User | None = None):
        if as_user:
            self.client.force_authenticate(as_user)
        return self.client.post(self.review_url, payload, format="json")

    # --- Authorization (FR3, Decision D-03) ---

    def test_unauthenticated_request_is_denied(self) -> None:
        """Unauthenticated caller cannot review documents."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            self.review_url, {"action": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_staff_user_is_forbidden(self) -> None:
        """Regular borrower/lender accounts cannot review documents (D-03)."""
        response = self.review({"action": "approve"}, as_user=self.submitter)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Approval (AC-106.1, AC-106.4) ---

    def test_admin_approval_persists_decision_and_audit(self) -> None:
        """AC-106.1: Approving sets status=approved and records reviewer + timestamp."""
        mail.outbox.clear()
        response = self.review({"action": "approve"}, as_user=self.admin)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "approved")
        self.assertEqual(self.document.reviewed_by, self.admin)
        self.assertIsNotNone(self.document.reviewed_at)
        self.assertEqual(self.document.rejection_reason, "")

    def test_approval_unlocks_identity_verified_gate(self) -> None:
        """AC-106.4: Approval makes user.has_verified_identity() True and unlocks gate."""
        self.assertFalse(self.submitter.has_verified_identity())

        self.review({"action": "approve"}, as_user=self.admin)

        self.submitter.refresh_from_db()
        self.assertTrue(self.submitter.has_verified_identity())

        request = _request_for(self.submitter)
        self.assertTrue(IsIdentityVerified().has_permission(request, None))

    def test_approval_sends_in_app_and_email_notification(self) -> None:
        """AC-106.3: Approval dispatches an in-app Notification and email."""
        from apps.notifications.constants import NOTIFICATION_TYPE_VERIFICATION_RESULT
        from apps.notifications.models import Notification

        mail.outbox.clear()
        Notification.objects.all().delete()

        self.review({"action": "approve"}, as_user=self.admin)

        # In-app notification
        notification = Notification.objects.filter(user=self.submitter).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.type.name, NOTIFICATION_TYPE_VERIFICATION_RESULT)
        self.assertEqual(notification.reference_id, str(self.document.pk))

        # Email notification
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn("Approved", sent_email.subject)
        self.assertIn(self.submitter.email, sent_email.to)
        self.assertIn("approved", sent_email.body.lower())

    # --- Rejection (AC-106.1, AC-106.2) ---

    def test_rejection_without_reason_is_rejected(self) -> None:
        """Rejecting requires a non-empty reason."""
        response = self.review(
            {"action": "reject", "rejection_reason": "   "},
            as_user=self.admin,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejection_reason", response.data)

    def test_admin_rejection_persists_decision_and_reason(self) -> None:
        """AC-106.1: Rejection persists status=rejected, reason, reviewer, and timestamp."""
        mail.outbox.clear()
        reason = "Photo is blurry and the ID expiration date is illegible."
        response = self.review(
            {"action": "reject", "rejection_reason": reason},
            as_user=self.admin,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "rejected")
        self.assertEqual(self.document.rejection_reason, reason)
        self.assertEqual(self.document.reviewed_by, self.admin)
        self.assertIsNotNone(self.document.reviewed_at)

        # User is still unverified
        self.assertFalse(self.submitter.has_verified_identity())

    def test_rejection_sends_in_app_and_email_notification_with_reason(self) -> None:
        """AC-106.3: Rejection notification includes the rejection reason."""
        from apps.notifications.constants import NOTIFICATION_TYPE_VERIFICATION_RESULT
        from apps.notifications.models import Notification

        mail.outbox.clear()
        reason = "Blurry photo. Please retake in good lighting."
        self.review(
            {"action": "reject", "rejection_reason": reason},
            as_user=self.admin,
        )

        # In-app notification
        notification = Notification.objects.filter(user=self.submitter).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.type.name, NOTIFICATION_TYPE_VERIFICATION_RESULT)

        # Email notification
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn(reason, sent_email.body)

    def test_resubmission_after_rejection_is_allowed(self) -> None:
        """AC-106.2: A rejected user may submit a new document."""
        # 1. Reject first document
        self.review(
            {"action": "reject", "rejection_reason": "Expired ID"},
            as_user=self.admin,
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "rejected")

        # 2. User resubmits with new document
        self.client.force_authenticate(self.submitter)
        submit_url = reverse("identity-document-submit")
        new_payload = {
            "document_type": "pup_id",
            "id_number": "2024-00123",
            "name_on_document": "Juan Dela Cruz",
            "document_file": png_upload("new_pup_id.png"),
            "consent_given": "true",
        }
        resubmit_response = self.client.post(
            submit_url, new_payload, format="multipart"
        )
        self.assertEqual(resubmit_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resubmit_response.data["status"], "pending")

        # Both records exist, latest is pending
        docs = IdentityDocument.objects.filter(user=self.submitter).order_by(
            "submitted_at"
        )
        self.assertEqual(docs.count(), 2)
        self.assertEqual(docs[0].status.name, "rejected")
        self.assertEqual(docs[1].status.name, "pending")

    def test_cannot_review_already_reviewed_document(self) -> None:
        """Attempting to re-review a finalized document returns 400 Bad Request."""
        self.review({"action": "approve"}, as_user=self.admin)

        # Try to review again
        second_response = self.review(
            {"action": "reject", "rejection_reason": "Changed mind"},
            as_user=self.admin,
        )
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been reviewed", str(second_response.data))

    def test_mail_outage_does_not_abort_review_transaction(self) -> None:
        """An email delivery failure is logged and swallowed; the review succeeds."""
        with mock.patch(
            "apps.users.services.send_mail", side_effect=OSError("smtp down")
        ):
            response = self.review({"action": "approve"}, as_user=self.admin)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "approved")

    def test_admin_approve_selected_documents_action(self) -> None:
        """IdentityDocumentAdmin batch action approves pending documents."""
        from django.contrib import admin

        model_admin = admin.site._registry[IdentityDocument]
        qs = IdentityDocument.objects.filter(pk=self.document.pk)

        request = _request_for(self.admin)
        model_admin.message_user = mock.MagicMock()

        model_admin.approve_selected_documents(request, qs)

        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "approved")
        self.assertEqual(self.document.reviewed_by, self.admin)
        self.assertIsNotNone(self.document.reviewed_at)


# ---------------------------------------------------------------------------
# CP-107 — Document protection, encryption at rest, and audit logging
# ---------------------------------------------------------------------------


class IdentityDocumentEncryptionTests(APITestCase):
    """
    CP-107 / FR3 / NFR 4.2: Fernet symmetric encryption for document bytes at rest.
    """

    def setUp(self) -> None:
        self.key = Fernet.generate_key().decode()

    def test_encrypt_decrypt_round_trip(self) -> None:
        """Data encrypted with configured key decrypts back to original bytes."""
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            encrypted = encrypt_document_data(PNG_BYTES)
            self.assertNotEqual(encrypted, PNG_BYTES)
            self.assertTrue(encrypted.startswith(b"gAAAAA"))
            decrypted = decrypt_document_data(encrypted)
            self.assertEqual(decrypted, PNG_BYTES)

    def test_tampered_ciphertext_raises_invalid_token(self) -> None:
        """Tampered bytes are detected and raise InvalidToken."""
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            encrypted = bytearray(encrypt_document_data(PNG_BYTES))
            encrypted[-5] ^= 0xFF
            with self.assertRaises(InvalidToken):
                decrypt_document_data(bytes(encrypted))

    def test_decrypt_with_wrong_key_raises_invalid_token(self) -> None:
        """Decrypting with a different key raises InvalidToken."""
        other_key = Fernet.generate_key().decode()
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            encrypted = encrypt_document_data(PNG_BYTES)
        with (
            override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=other_key),
            self.assertRaises(InvalidToken),
        ):
            decrypt_document_data(encrypted)

    def test_empty_or_none_bytes_pass_through_cleanly(self) -> None:
        """Empty inputs return empty bytes."""
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            self.assertEqual(encrypt_document_data(b""), b"")
            self.assertEqual(encrypt_document_data(None), b"")
            self.assertEqual(decrypt_document_data(b""), b"")
            self.assertEqual(decrypt_document_data(None), b"")

    def test_no_key_in_dev_test_passes_through_plaintext(self) -> None:
        """When key is unconfigured in development/test, bytes pass through."""
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY="", DEBUG=True):
            self.assertEqual(encrypt_document_data(PNG_BYTES), PNG_BYTES)
            self.assertEqual(decrypt_document_data(PNG_BYTES), PNG_BYTES)

    def test_missing_key_in_production_fails_closed(self) -> None:
        """In production (DEBUG=False, non-sqlite DB) unset key raises ImproperlyConfigured."""
        with (
            override_settings(
                IDENTITY_DOCUMENT_ENCRYPTION_KEY="",
                DEBUG=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.postgresql"}},
            ),
            self.assertRaises(ImproperlyConfigured),
        ):
            encrypt_document_data(PNG_BYTES)

    def test_invalid_key_raises_improperly_configured(self) -> None:
        """A malformed encryption key raises ImproperlyConfigured."""
        with (
            override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY="not-a-fernet-key"),
            self.assertRaises(ImproperlyConfigured),
        ):
            encrypt_document_data(PNG_BYTES)


@in_memory_storage
class IdentityDocumentSubmissionEncryptionTests(APITestCase):
    """
    CP-107: Verification that document submission stores encrypted ciphertext in DB.
    """

    def setUp(self) -> None:
        self.key = Fernet.generate_key().decode()
        self.submit_url = reverse("identity-document-submit")
        self.user = make_user("encrypted-submitter@iskolarngbayan.pup.edu.ph")
        self.client.force_authenticate(self.user)

    def test_submission_stores_encrypted_bytes_when_key_configured(self) -> None:
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            payload = {
                "document_type": "pup_id",
                "id_number": "2024-99991",
                "name_on_document": "Juan Dela Cruz",
                "document_file": png_upload(),
                "consent_given": "true",
            }
            response = self.client.post(self.submit_url, payload, format="multipart")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            doc = IdentityDocument.objects.get(user=self.user)
            raw_stored = bytes(doc.document_data)
            self.assertNotEqual(raw_stored, PNG_BYTES)
            self.assertTrue(raw_stored.startswith(b"gAAAAA"))
            self.assertEqual(decrypt_document_data(raw_stored), PNG_BYTES)


class IdentityDocumentDownloadTests(APITestCase):
    """
    CP-107: Secure document download endpoint (admin-only, logged).
    GET /api/v1/identity/documents/<pk>/download/
    """

    def setUp(self) -> None:
        self.key = Fernet.generate_key().decode()
        self.admin = make_user(
            "admin-doc-viewer@iskolarngbayan.pup.edu.ph", is_staff=True
        )
        self.regular_user = make_user("regular-user@iskolarngbayan.pup.edu.ph")
        self.owner = make_user("owner@iskolarngbayan.pup.edu.ph")

        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            encrypted_data = encrypt_document_data(PNG_BYTES)

        self.document = IdentityDocument.objects.create(
            user=self.owner,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-88888",
            document_data=encrypted_data,
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )
        self.url = reverse("identity-document-download", args=[self.document.pk])

    def test_admin_can_download_and_decrypts_document(self) -> None:
        """Admin receives the original plaintext bytes with proper content headers."""
        self.client.force_authenticate(self.admin)
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, PNG_BYTES)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("2024-88888", response["Content-Disposition"])

    def test_download_supports_session_authentication(self) -> None:
        """Admin authenticated via session (e.g. Django Admin browser) can download."""
        self.client.force_login(self.admin)
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, PNG_BYTES)

    def test_download_content_type_detection(self) -> None:
        """MIME type is detected from file signatures (JPEG, PDF)."""
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            doc_jpg = IdentityDocument.objects.create(
                user=self.owner,
                document_type=IdentityDocumentType.objects.get(name="government_id"),
                id_number="2024-88889",
                document_data=encrypt_document_data(b"\xff\xd8\xff\xe0\x00\x10JFIF"),
                status=IdentityDocumentStatus.objects.get(name="pending"),
            )
        url_jpg = reverse("identity-document-download", args=[doc_jpg.pk])
        self.client.force_authenticate(self.admin)
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            res = self.client.get(url_jpg)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "image/jpeg")

    def test_download_creates_audit_log_entry(self) -> None:
        """Admin download creates an immutable AdminAccessLog row with action='download'."""
        self.client.force_authenticate(self.admin)
        with override_settings(IDENTITY_DOCUMENT_ENCRYPTION_KEY=self.key):
            response = self.client.get(self.url, REMOTE_ADDR="198.51.100.42")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AdminAccessLog.objects.filter(
            document=self.document, admin=self.admin
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, "download")
        self.assertEqual(log.ip_address, "198.51.100.42")

    def test_non_admin_cannot_download_document(self) -> None:
        """Regular authenticated user gets 403 Forbidden."""
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(AdminAccessLog.objects.filter(document=self.document).exists())

    def test_document_owner_cannot_download_via_admin_endpoint(self) -> None:
        """Even the owner of the document cannot access the admin download endpoint."""
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_download(self) -> None:
        """Anonymous caller gets 401 Unauthorized."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_existent_document_returns_404(self) -> None:
        """Request for non-existent pk returns 404."""
        self.client.force_authenticate(self.admin)
        missing_url = reverse("identity-document-download", args=[999999])
        response = self.client.get(missing_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_document_without_data_returns_404(self) -> None:
        """Document with empty document_data returns 404."""
        empty_doc = IdentityDocument.objects.create(
            user=self.regular_user,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-00000",
            document_data=b"",
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )
        url = reverse("identity-document-download", args=[empty_doc.pk])
        self.client.force_authenticate(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class IdentityDocumentOwnerInfoTests(APITestCase):
    """
    CP-107: Admin-mediated contact release endpoint (FR3).
    GET /api/v1/identity/documents/<pk>/owner-info/
    """

    def setUp(self) -> None:
        self.admin = make_user("admin-contact@iskolarngbayan.pup.edu.ph", is_staff=True)
        self.regular_user = make_user("regular-user2@iskolarngbayan.pup.edu.ph")
        self.owner = make_user(
            "owner2@iskolarngbayan.pup.edu.ph",
            full_name="Maria Santos",
            contact_number="09171234567",
        )
        self.document = IdentityDocument.objects.create(
            user=self.owner,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-77777",
            document_data=b"secret-bytes",
            status=IdentityDocumentStatus.objects.get(name="approved"),
        )
        self.url = reverse("identity-document-owner-info", args=[self.document.pk])

    def test_admin_can_retrieve_owner_contact_info(self) -> None:
        """Admin receives owner's name and contact details, never document or ID number."""
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url, REMOTE_ADDR="203.0.113.195")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "Maria Santos")
        self.assertEqual(response.data["email"], "owner2@iskolarngbayan.pup.edu.ph")
        self.assertEqual(response.data["contact_number"], "09171234567")
        self.assertEqual(response.data["affiliation"], "Student")

        # Confidential / auth fields must never be exposed
        self.assertNotIn("document_data", response.data)
        self.assertNotIn("id_number", response.data)
        self.assertNotIn("password", response.data)

        log = AdminAccessLog.objects.filter(
            document=self.document, admin=self.admin, action="contact_release"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.ip_address, "203.0.113.195")

    def test_non_admin_cannot_access_owner_info(self) -> None:
        """Regular users cannot access owner info."""
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_access_owner_info(self) -> None:
        """Anonymous callers get 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminAccessLogTests(APITestCase):
    """
    CP-107 / FR14: Audit logging of administrative access to identity documents.
    """

    def setUp(self) -> None:
        self.admin = make_user("admin-audit@iskolarngbayan.pup.edu.ph", is_staff=True)
        self.submitter = make_user("submitter-audit@iskolarngbayan.pup.edu.ph")
        self.document = IdentityDocument.objects.create(
            user=self.submitter,
            document_type=IdentityDocumentType.objects.get(name="pup_id"),
            id_number="2024-33333",
            document_data=PNG_BYTES,
            status=IdentityDocumentStatus.objects.get(name="pending"),
        )

    def test_review_endpoint_creates_audit_log(self) -> None:
        """Calling the review endpoint records an AdminAccessLog with action='review'."""
        self.client.force_authenticate(self.admin)
        url = reverse("identity-document-review", args=[self.document.pk])
        response = self.client.post(
            url,
            {"action": "approve"},
            REMOTE_ADDR="192.0.2.1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AdminAccessLog.objects.filter(
            document=self.document, admin=self.admin, action="review"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.ip_address, "192.0.2.1")

    def test_django_admin_change_view_creates_audit_log(self) -> None:
        """Opening document detail in Django Admin logs an action='view'."""
        from django.contrib import admin
        from django.test import RequestFactory

        model_admin = admin.site._registry[IdentityDocument]
        request = RequestFactory().get(
            f"/admin/users/identitydocument/{self.document.pk}/change/"
        )
        request.user = self.admin
        request.META["REMOTE_ADDR"] = "192.0.2.100"

        with (
            mock.patch.object(model_admin, "get_object", return_value=self.document),
            mock.patch(
                "django.contrib.admin.ModelAdmin.change_view",
                return_value=mock.MagicMock(),
            ),
        ):
            model_admin.change_view(request, str(self.document.pk))

        log = AdminAccessLog.objects.filter(
            document=self.document, admin=self.admin, action="view"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.ip_address, "192.0.2.100")

    def test_admin_download_link_renders_html_link(self) -> None:
        """download_link on IdentityDocumentAdmin produces expected HTML anchor."""
        from django.contrib import admin

        model_admin = admin.site._registry[IdentityDocument]
        html = model_admin.download_link(self.document)
        self.assertIn("Download Document", str(html))
        self.assertIn(
            f"/api/v1/identity/documents/{self.document.pk}/download/", str(html)
        )

    def test_admin_access_log_admin_is_immutable(self) -> None:
        """AdminAccessLogAdmin blocks add, change, and delete operations."""
        from django.contrib import admin

        model_admin = admin.site._registry[AdminAccessLog]
        request = _request_for(self.admin)

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_admin_access_log_model_str(self) -> None:
        """String representation of access log is human readable."""
        log = AdminAccessLog.objects.create(
            document=self.document,
            admin=self.admin,
            action="view",
            ip_address="127.0.0.1",
        )
        s = str(log)
        self.assertIn("View", s)
        self.assertIn(str(self.document.id), s)
        self.assertIn(self.admin.full_name, s)
