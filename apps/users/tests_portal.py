"""
Portal tests (BE-BUG-0006): server-rendered CoPUPAdmin verification workflow.

Covers screens 76 (sign-in), 77 (dashboard), 82 (verification queue),
83 (verification review) and 84 (reject overlay). Uses Django's `TestCase`
client because the portal is regular session-based Django pages, not DRF.

Authority is `is_staff` (D-03): the sign-in rejects non-staff, and every
staff-gated page logs a non-staff member out.
"""

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AdminAccessLog
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.notifications.models import Notification
from apps.reports.models import UserReport, UserReportCategory
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
)

from .tests import PNG_BYTES, make_user


def make_document(
    user,
    *,
    id_number: str = "2024-00100-MN-0",
    document_type_name: str = "pup_id",
    status_name: str = "pending",
):
    return IdentityDocument.objects.create(
        user=user,
        document_type=IdentityDocumentType.objects.get(name=document_type_name),
        id_number=id_number,
        document_data=PNG_BYTES,
        status=IdentityDocumentStatus.objects.get(name=status_name),
    )


class PortalAccessTests(TestCase):
    """Screens 76 / staff gating: only administrator accounts get in."""

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-portal@iskolarngbayan.pup.edu.ph",
            is_staff=True,
            full_name="Ash Reyes",
        )
        self.member = make_user(
            "member-portal@iskolarngbayan.pup.edu.ph", full_name="Bela Cruz"
        )
        self.document = make_document(self.member)

    def test_login_page_loads(self) -> None:
        response = self.client.get(reverse("portal-login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administrator Portal")
        self.assertContains(response, "Only administrator accounts can sign in here.")

    def test_login_rejects_non_staff_account(self) -> None:
        response = self.client.post(
            reverse("portal-login"),
            {"username": self.member.email, "password": "StrongPassword123!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only administrator accounts can sign in here.")
        self.assertEqual(self.client.session.get("_auth_user_id"), None)

    def test_login_allows_staff_redirects_to_dashboard(self) -> None:
        response = self.client.post(
            reverse("portal-login"),
            {"username": self.admin.email, "password": "StrongPassword123!"},
        )
        self.assertRedirects(response, reverse("portal-dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)

    def test_portal_pages_redirect_anonymous_to_sign_in(self) -> None:
        for url in (
            reverse("portal-dashboard"),
            reverse("portal-verification-queue"),
            reverse("portal-verification-review", args=[self.document.pk]),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)

    def test_non_staff_member_is_logged_out_of_portal(self) -> None:
        self.client.force_login(self.member)
        response = self.client.get(reverse("portal-dashboard"))
        self.assertRedirects(response, reverse("portal-login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class PortalDashboardTests(TestCase):
    """Screen 77: stat cards, orders-by-status and activity feed."""

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-dash@iskolarngbayan.pup.edu.ph", is_staff=True, full_name="Ash Reyes"
        )
        self.client.force_login(self.admin)
        self.member = make_user("dash-member@iskolarngbayan.pup.edu.ph")
        make_document(self.member)

    def test_dashboard_renders_relevant_figures(self) -> None:
        response = self.client.get(reverse("portal-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total Users")
        self.assertContains(response, "Pending Verifications")
        self.assertContains(response, "Orders by Status")
        self.assertContains(response, "Ash Reyes")


class PortalVerificationQueueTests(TestCase):
    """Screen 82: tabs, table rows, pagination."""

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-queue@iskolarngbayan.pup.edu.ph",
            is_staff=True,
            full_name="Ash Reyes",
        )
        self.client.force_login(self.admin)
        self.member = make_user(
            "queue-member@iskolarngbayan.pup.edu.ph", full_name="Bela Cruz"
        )
        make_document(self.member, id_number="2024-99100")

    def test_queue_renders_pending_tab_with_submission(self) -> None:
        response = self.client.get(reverse("portal-verification-queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Review")
        self.assertContains(response, "Bela Cruz")
        self.assertContains(response, "PUP ID")
        self.assertContains(response, "Review")

    def test_queue_tab_counts_reflect_each_status(self) -> None:
        approved = make_user("queue-approved@iskolarngbayan.pup.edu.ph")
        make_document(approved, id_number="2024-99101", status_name="approved")
        rejected = make_user("queue-rejected@iskolarngbayan.pup.edu.ph")
        make_document(rejected, id_number="2024-99102", status_name="rejected")

        response = self.client.get(reverse("portal-verification-queue"))
        self.assertContains(response, "Pending Review (1)")
        self.assertContains(response, "Approved (1)")
        self.assertContains(response, "Rejected (1)")

    def test_queue_filters_by_tab(self) -> None:
        approved = make_user(
            "queue-approved2@iskolarngbayan.pup.edu.ph", full_name="Mina Ocampo"
        )
        make_document(approved, id_number="2024-99103", status_name="approved")

        response = self.client.get(
            reverse("portal-verification-queue"), {"status": "approved"}
        )
        self.assertContains(response, "Mina Ocampo")
        self.assertNotContains(response, "Bela Cruz")
        response_pending = self.client.get(
            reverse("portal-verification-queue"), {"status": "pending"}
        )
        self.assertContains(response_pending, "Bela Cruz")
        self.assertNotContains(response_pending, "Mina Ocampo")

    def test_queue_paginates(self) -> None:
        emails = [f"queue-page-{i}@iskolarngbayan.pup.edu.ph" for i in range(7)]
        for index, email in enumerate(emails, start=1):
            member = make_user(email)
            make_document(member, id_number=f"2024-99{index + 100}")

        response = self.client.get(reverse("portal-verification-queue"))
        self.assertContains(response, "Showing 1 to 6 of 8 results")
        response_page_2 = self.client.get(
            reverse("portal-verification-queue"), {"page": 2}
        )
        self.assertEqual(response_page_2.status_code, 200)


class PortalVerificationReviewTests(TestCase):
    """Screens 83/84: document, checks, approve/reject via buttons."""

    def setUp(self) -> None:
        self.key_email = "admin-review@iskolarngbayan.pup.edu.ph"
        self.admin = make_user(self.key_email, is_staff=True, full_name="Ash Reyes")
        self.member = make_user(
            "review-member@iskolarngbayan.pup.edu.ph",
            full_name="Bela Cruz",
            account_status="active",
        )
        self.document = make_document(self.member, id_number="2024-77200-MN-0")
        self.client.force_login(self.admin)

    def test_review_page_shows_document_name_and_details(self) -> None:
        url = reverse("portal-verification-review", args=[self.document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verification Review")
        self.assertContains(response, "Bela Cruz")
        self.assertContains(response, "Submitted ID")
        self.assertContains(response, "Matches the ID and account name")
        self.assertContains(response, "Consent recorded: ID storage")

    def test_review_page_confirms_a_well_formed_pup_id(self) -> None:
        response = self.client.get(
            reverse("portal-verification-review", args=[self.document.pk])
        )

        check = self._format_check(response)
        self.assertTrue(check["pass"])
        self.assertContains(response, "ID number uses the PUP format")
        self.assertContains(response, "2024-77200-MN-0")

    def test_review_page_flags_a_malformed_pup_id(self) -> None:
        """BE-BUG-2005: legacy or mistyped numbers lose the campus segment."""
        self.document.id_number = "2024-77200"
        self.document.save(update_fields=["id_number"])
        response = self.client.get(
            reverse("portal-verification-review", args=[self.document.pk])
        )

        check = self._format_check(response)
        self.assertFalse(check["pass"])

    def test_government_id_skips_the_pup_format_check(self) -> None:
        self.document.document_type = IdentityDocumentType.objects.get(
            name="government_id"
        )
        self.document.id_number = "N01-23-456789"
        self.document.save(update_fields=["document_type", "id_number"])
        response = self.client.get(
            reverse("portal-verification-review", args=[self.document.pk])
        )

        self.assertNotContains(response, "ID number uses the PUP format")

    def _format_check(self, response) -> dict:
        return next(
            check
            for check in response.context["checks"]
            if check["label"].startswith("ID number uses the PUP format")
        )

    def test_viewing_page_logs_an_audit_entry(self) -> None:
        url = reverse("portal-verification-review", args=[self.document.pk])
        self.client.get(url)
        log = AdminAccessLog.objects.get(
            document=self.document, admin=self.admin, action="view"
        )
        self.assertIsNotNone(log)

    def test_approve_button_marks_document_approved(self) -> None:
        url = reverse("portal-verification-review-submit", args=[self.document.pk])
        response = self.client.post(url, {"action": "approve"})
        self.assertRedirects(response, reverse("portal-verification-queue"))

        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "approved")
        self.assertEqual(self.document.reviewed_by, self.admin)
        self.assertEqual(self.document.rejection_reason, "")
        self.assertTrue(
            AdminAccessLog.objects.filter(
                document=self.document, admin=self.admin, action="review"
            ).exists()
        )
        self.assertTrue(Notification.objects.filter(user=self.member).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_reject_without_reason_is_refused(self) -> None:
        url = reverse("portal-verification-review-submit", args=[self.document.pk])
        response = self.client.post(url, {"action": "reject", "rejection_reason": "  "})
        self.assertRedirects(
            response, reverse("portal-verification-review", args=[self.document.pk])
        )

        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "pending")
        self.assertFalse(AdminAccessLog.objects.filter(action="review").exists())

    def test_reject_requires_reason_and_stores_it(self) -> None:
        url = reverse("portal-verification-review-submit", args=[self.document.pk])
        response = self.client.post(
            url, {"action": "reject", "rejection_reason": "Photo is blurry."}
        )
        self.assertRedirects(response, reverse("portal-verification-queue"))

        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "rejected")
        self.assertEqual(self.document.rejection_reason, "Photo is blurry.")
        self.assertTrue(
            AdminAccessLog.objects.filter(
                document=self.document, action="review"
            ).exists()
        )

    def test_reviewed_document_cannot_be_reviewed_again(self) -> None:
        self.client.post(
            reverse("portal-verification-review-submit", args=[self.document.pk]),
            {"action": "reject", "rejection_reason": "Photo is blurry."},
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "rejected")

        second = self.client.post(
            reverse("portal-verification-review-submit", args=[self.document.pk]),
            {"action": "approve"},
        )
        self.assertRedirects(
            second,
            reverse("portal-verification-review", args=[self.document.pk]),
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.status.name, "rejected")


class PickupLocationPortalTests(TestCase):
    """CP-1108: portal mirror of CP-1105 -- staff manage fixed locations."""

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-pickup@iskolarngbayan.pup.edu.ph",
            is_staff=True,
            full_name="Ash Reyes",
        )
        self.member = make_user(
            "member-pickup@iskolarngbayan.pup.edu.ph", full_name="Bela Cruz"
        )
        self.main = PickupLocation.objects.create(
            name="Main Library Front Desk",
            description="Beside the circulation counter",
        )
        self.lobby = PickupLocation.objects.create(name="Engineering Lobby")
        self.old = PickupLocation.objects.create(name="Old Gym Entrance")
        self.old.deleted_at = timezone.now()
        self.old.save(update_fields=["deleted_at"])
        self.url = reverse("portal-pickup-locations")

    def test_anonymous_redirected_to_sign_in(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_non_staff_member_is_logged_out(self) -> None:
        self.client.force_login(self.member)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("portal-login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_list_splits_active_and_archived(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        active_names = [loc.name for loc in response.context["locations"]]
        self.assertEqual(active_names, ["Engineering Lobby", "Main Library Front Desk"])
        archived_names = [loc.name for loc in response.context["archived"]]
        self.assertEqual(archived_names, ["Old Gym Entrance"])
        self.assertContains(response, "Main Library Front Desk")
        self.assertContains(response, "Old Gym Entrance")
        self.assertContains(response, self.url)

    def test_actions_read_remove_not_archive(self) -> None:
        """BE-BUG-2003: the review action matches the user story wording."""
        self.client.force_login(self.admin)
        response = self.client.get(self.url)

        self.assertContains(response, ">Remove<")
        self.assertContains(response, "Removed (1)")
        self.assertContains(response, 'class="row-actions"')
        self.assertNotContains(response, "Archive")

    def test_remove_reports_the_new_wording(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal-pickup-location-delete", args=[self.lobby.pk]),
            follow=True,
        )
        self.assertContains(response, "removed.")

    def test_nav_link_is_enabled_on_shell(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.get(reverse("portal-dashboard"))
        self.assertContains(response, self.url)

    def test_create_trims_name_and_feeds_api_dropdown(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url,
            {"name": "  Student Center Counter  ", "description": "2nd floor"},
        )
        self.assertRedirects(response, self.url)

        created = PickupLocation.objects.get(name="Student Center Counter")
        self.assertEqual(created.description, "2nd floor")

        # The API's exact dropdown queryset must now contain the new row.
        dropdown = PickupLocation.objects.filter(deleted_at__isnull=True).order_by(
            "name"
        )
        self.assertIn(created, list(dropdown))

        api = APIClient()
        api.force_authenticate(user=self.admin)
        payload = api.get("/api/v1/pickup-locations/")
        self.assertEqual(payload.status_code, 200)
        self.assertIn("Student Center Counter", [row["name"] for row in payload.data])

    def test_blank_name_rejected_with_serializer_wording(self) -> None:
        self.client.force_login(self.admin)
        before = PickupLocation.objects.count()
        response = self.client.post(self.url, {"name": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Location name cannot be blank.")
        self.assertEqual(PickupLocation.objects.count(), before)

    def test_edit_updates_active_location(self) -> None:
        self.client.force_login(self.admin)
        edit_url = reverse("portal-pickup-location-edit", args=[self.main.pk])

        page = self.client.get(edit_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'value="Main Library Front Desk"')

        response = self.client.post(
            edit_url,
            {"name": "Main Library Desk (North Wing)", "description": "New spot"},
        )
        self.assertRedirects(response, self.url)
        self.main.refresh_from_db()
        self.assertEqual(self.main.name, "Main Library Desk (North Wing)")
        self.assertEqual(self.main.description, "New spot")

    def test_edit_archived_location_is_404(self) -> None:
        self.client.force_login(self.admin)
        edit_url = reverse("portal-pickup-location-edit", args=[self.old.pk])
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 404)

    def test_soft_delete_archives_location(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal-pickup-location-delete", args=[self.lobby.pk])
        )
        self.assertRedirects(response, self.url)
        self.lobby.refresh_from_db()
        self.assertIsNotNone(self.lobby.deleted_at)
        self.assertNotIn(
            self.lobby.pk,
            [loc.pk for loc in PickupLocation.objects.filter(deleted_at__isnull=True)],
        )

    def test_restore_returns_location_to_active(self) -> None:
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal-pickup-location-restore", args=[self.old.pk])
        )
        self.assertRedirects(response, self.url)
        self.old.refresh_from_db()
        self.assertIsNone(self.old.deleted_at)

    def test_delete_and_restore_reject_get(self) -> None:
        self.client.force_login(self.admin)
        delete_url = reverse("portal-pickup-location-delete", args=[self.lobby.pk])
        restore_url = reverse("portal-pickup-location-restore", args=[self.old.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 405)
        self.assertEqual(self.client.get(restore_url).status_code, 405)


class PortalListingCategoryTests(TestCase):
    """
    Configuration > Categories: the pick list a Lender publishes from.

    Categories gate listing creation (CP-401), and the mobile app only reads
    them, so the administrator fills the list in here.
    """

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-categories@iskolarngbayan.pup.edu.ph",
            is_staff=True,
            full_name="Ash Reyes",
        )
        self.client.force_login(self.admin)
        self.url = reverse("portal-listing-categories")

    def test_page_loads_with_the_empty_state(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a category")
        self.assertContains(response, "No categories yet.")

    def test_add_creates_a_category(self) -> None:
        response = self.client.post(
            self.url, {"name": "Textbooks", "description": "Course books"}
        )

        self.assertRedirects(response, self.url)
        category = ListingCategory.objects.get(name="Textbooks")
        self.assertEqual(category.description, "Course books")

    def test_blank_name_is_rejected(self) -> None:
        response = self.client.post(self.url, {"name": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Category name cannot be blank.")
        self.assertEqual(ListingCategory.objects.count(), 0)

    def test_duplicate_name_is_rejected(self) -> None:
        ListingCategory.objects.create(name="Textbooks")

        response = self.client.post(self.url, {"name": "textbooks"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(ListingCategory.objects.count(), 1)

    def test_edit_renames_a_category(self) -> None:
        category = ListingCategory.objects.create(name="Textbooks")
        edit_url = reverse("portal-listing-category-edit", args=[category.pk])

        page = self.client.get(edit_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'value="Textbooks"')

        response = self.client.post(
            edit_url, {"name": "Books", "description": "Every book"}
        )
        self.assertRedirects(response, self.url)
        category.refresh_from_db()
        self.assertEqual(category.name, "Books")
        self.assertEqual(category.description, "Every book")

    def test_edit_accepts_the_name_it_already_has(self) -> None:
        category = ListingCategory.objects.create(name="Textbooks")
        edit_url = reverse("portal-listing-category-edit", args=[category.pk])

        response = self.client.post(edit_url, {"name": "Textbooks"})

        self.assertRedirects(response, self.url)
        self.assertEqual(ListingCategory.objects.count(), 1)

    def test_delete_removes_an_unused_category(self) -> None:
        category = ListingCategory.objects.create(name="Textbooks")

        response = self.client.post(
            reverse("portal-listing-category-delete", args=[category.pk])
        )

        self.assertRedirects(response, self.url)
        self.assertFalse(ListingCategory.objects.filter(pk=category.pk).exists())

    def test_delete_is_refused_while_a_listing_uses_the_category(self) -> None:
        category = ListingCategory.objects.create(name="Textbooks")
        lender = make_user(
            "lender-categories@iskolarngbayan.pup.edu.ph",
            full_name="Bela Cruz",
        )
        Listing.objects.create(
            lender=lender,
            title="Calculus: Early Transcendentals",
            description="Complete calculus reference in good condition.",
            category=category,
            condition="Good",
            pickup_location=PickupLocation.objects.create(name="Main Library"),
            rate_per_day="25.00",
            is_ownership_confirmed=True,
            status=ListingStatus.objects.create(name="active"),
        )

        response = self.client.post(
            reverse("portal-listing-category-delete", args=[category.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be deleted")
        self.assertTrue(ListingCategory.objects.filter(pk=category.pk).exists())

    def test_delete_rejects_get(self) -> None:
        category = ListingCategory.objects.create(name="Textbooks")
        delete_url = reverse("portal-listing-category-delete", args=[category.pk])

        self.assertEqual(self.client.get(delete_url).status_code, 405)

    def test_page_requires_an_administrator(self) -> None:
        member = make_user("member-categories@iskolarngbayan.pup.edu.ph")
        self.client.force_login(member)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("portal-login"))


class PortalSidebarTests(TestCase):
    """
    The sidebar names each admin capability after the sprint ticket and test
    cases it covers, and says which ticket will switch it on (D-31).
    """

    def setUp(self) -> None:
        self.admin = make_user(
            "admin-sidebar@iskolarngbayan.pup.edu.ph",
            is_staff=True,
            full_name="Ash Reyes",
        )
        self.client.force_login(self.admin)

    def test_sidebar_groups_follow_the_sprints(self) -> None:
        response = self.client.get(reverse("portal-dashboard"))

        self.assertEqual(response.status_code, 200)
        for group in (
            "Overview",
            "Verification",
            "Configuration",
            "Moderation",
            "System",
        ):
            self.assertContains(response, f">{group}")

    def test_live_sections_are_linked(self) -> None:
        response = self.client.get(reverse("portal-dashboard"))

        self.assertContains(response, reverse("portal-verification-queue"))
        self.assertContains(response, reverse("portal-listing-categories"))
        self.assertContains(response, reverse("portal-pickup-locations"))

    def test_locked_sections_carry_their_ticket(self) -> None:
        response = self.client.get(reverse("portal-dashboard"))

        for ticket in ("CP-1109", "CP-1110", "CP-1111", "CP-1112", "CP-1113", "CP-903"):
            self.assertContains(response, ticket)

    def test_locked_sections_are_not_links(self) -> None:
        response = self.client.get(reverse("portal-dashboard"))

        self.assertContains(response, "Users &amp; Roles")
        self.assertContains(response, "Reports &amp; Flags")
        self.assertContains(response, "Listings &amp; Reviews")
        self.assertContains(response, "Unreturned Cases")
        self.assertContains(response, "Disputes")
        self.assertContains(response, "System Parameters")
        self.assertContains(response, "Audit Log")

    def test_reports_badge_counts_open_reports(self) -> None:
        reporter = make_user("reporter-sidebar@iskolarngbayan.pup.edu.ph")
        target = make_user("target-sidebar@iskolarngbayan.pup.edu.ph")
        category = UserReportCategory.objects.create(name="Harassment")
        UserReport.objects.create(
            reporter=reporter,
            target_user=target,
            category=category,
            description="Repeated abusive messages.",
        )

        response = self.client.get(reverse("portal-dashboard"))

        self.assertContains(response, '<span class="nav-badge">1</span>', html=True)

    def test_reports_badge_ignores_resolved_reports(self) -> None:
        reporter = make_user("reporter-resolved@iskolarngbayan.pup.edu.ph")
        target = make_user("target-resolved@iskolarngbayan.pup.edu.ph")
        category = UserReportCategory.objects.create(name="Spam")
        UserReport.objects.create(
            reporter=reporter,
            target_user=target,
            category=category,
            description="Already handled.",
            status="resolved",
        )

        response = self.client.get(reverse("portal-dashboard"))

        self.assertNotContains(response, 'class="nav-badge"')
