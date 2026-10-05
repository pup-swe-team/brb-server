from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

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
            "Registration successful. Your account is pending verification.",
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
