from django import forms
from django.contrib import admin
from django.contrib.admin import helpers
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.audit.services import log_admin_document_access

from .models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)
from .services import deactivate_account, deactivation_blockers


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """
    Read/manage accounts from /admin/ (ops visibility; FR14-adjacent).

    The password hash is excluded from the form -- credential changes go
    through the app's own endpoints (CP-104/1001), not the admin. Account
    and lender statuses are editable here so support can resolve incidents
    without raw SQL; D-03 authority remains `is_staff`/`is_superuser`.
    """

    list_display = (
        "email",
        "full_name",
        "affiliation",
        "account_status",
        "lender_status",
        "is_staff",
        "is_active",
        "created_at",
    )
    list_filter = ("affiliation", "account_status", "lender_status", "is_staff")
    search_fields = ("email", "full_name")
    exclude = ("password",)
    readonly_fields = (
        "last_login",
        "date_joined",
        "created_at",
        "updated_at",
        "email_verified_at",
        "email_verification_sent_at",
        "password_reset_sent_at",
        "email_change_sent_at",
    )
    date_hierarchy = "created_at"
    actions = ("deactivate_selected_accounts", "reactivate_selected_accounts")

    @admin.action(description="Deactivate selected accounts (CP-1004)")
    def deactivate_selected_accounts(self, request, queryset) -> None:
        """
        The same close-out members can trigger themselves: status to
        `deactivated`, `is_active` off, live tokens blacklisted. Accounts with
        open orders or unreturned-item cases are skipped because those must be
        settled first (CP-1004); administrators and the acting user are never
        targets.
        """
        eligible = queryset.filter(is_active=True, is_superuser=False).exclude(
            pk=request.user.pk
        )
        deactivated = 0
        blocked = 0
        for user in eligible:
            if any(deactivation_blockers(user).values()):
                blocked += 1
                continue
            deactivate_account(user)
            deactivated += 1

        skipped = queryset.count() - eligible.count()
        message = f"Deactivated {deactivated} account(s)."
        if blocked:
            message += f" {blocked} skipped: open orders or unreturned-item cases."
        if skipped:
            message += (
                f" {skipped} skipped: already inactive, an administrator, or you."
            )
        self.message_user(request, message)

    @admin.action(description="Reactivate selected accounts (undo CP-1004)")
    def reactivate_selected_accounts(self, request, queryset) -> None:
        """Only `deactivated` accounts are restored; suspensions stay in place."""
        reactivated = queryset.filter(
            account_status=User.AccountStatusChoices.DEACTIVATED
        ).update(
            account_status=User.AccountStatusChoices.ACTIVE,
            is_active=True,
            updated_at=timezone.now(),
        )
        self.message_user(request, f"Reactivated {reactivated} account(s).")


class RejectIdentityDocumentForm(forms.Form):
    """Admin-only form collecting the mandatory rejection reason (CP-106, TC-022)."""

    rejection_reason = forms.CharField(
        label="Rejection reason",
        widget=forms.Textarea(attrs={"rows": 4, "cols": 60}),
        help_text="Required. This text is sent to the submitter in the notification.",
    )

    def clean_rejection_reason(self) -> str:
        reason = self.cleaned_data["rejection_reason"].strip()
        if not reason:
            raise forms.ValidationError("A rejection reason is required.")
        return reason


class IdentityDocumentTypeAdmin(admin.ModelAdmin):
    """Lookup table seeded by migration 0004; editable so new types can be added."""

    list_display = ("name",)


class IdentityDocumentStatusAdmin(admin.ModelAdmin):
    """Lookup table seeded by migration 0004.

    Editing is off by default because `has_verified_identity()` and the CP-106
    approval flow match on the literal name `approved`. Renaming a row would
    silently change verification behaviour, so it takes a deliberate code change.
    """

    list_display = ("name",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(IdentityDocument)
class IdentityDocumentAdmin(admin.ModelAdmin):
    """
    Administrator-only view of submitted identity documents (FR3, FR14, NFR 4.2).

    Raw document bytes are stored encrypted at rest (CP-107).
    Viewing an identity document record or downloading its bytes is logged to
    AdminAccessLog (FR14). The raw blob is omitted from list display and detail
    fields in favor of a secure, logged download link.
    """

    list_display = (
        "id",
        "user",
        "document_type",
        "id_number",
        "status",
        "has_profile_mismatch",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status", "document_type", "has_profile_mismatch", "submitted_at")
    search_fields = ("id_number", "user__email", "user__full_name", "name_on_document")
    readonly_fields = (
        "user",
        "document_type",
        "id_number",
        "download_link",
        "status",
        "name_on_document",
        "has_profile_mismatch",
        "consent_given",
        "consented_at",
        "rejection_reason",
        "reviewed_by",
        "reviewed_at",
        "submitted_at",
    )
    date_hierarchy = "submitted_at"
    actions = ("approve_selected_documents", "reject_selected_documents")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        document = self.get_object(request, object_id)
        if document is not None:
            log_admin_document_access(
                document=document,
                admin=request.user,
                action="view",
                request=request,
            )
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.action(description="Approve selected identity documents")
    def approve_selected_documents(self, request, queryset):
        from .services import review_identity_document

        count = 0
        for doc in queryset.filter(status__name="pending"):
            review_identity_document(
                document=doc,
                reviewer=request.user,
                action="approve",
                request=request,
            )
            count += 1
        self.message_user(request, f"Approved {count} identity document(s).")

    @admin.action(description="Reject selected identity documents")
    def reject_selected_documents(self, request, queryset):
        """Reject pending documents after collecting a mandatory reason (TC-022)."""
        from .services import review_identity_document

        pending = queryset.filter(status__name="pending")

        if request.POST.get("_reject_confirmed"):
            form = RejectIdentityDocumentForm(request.POST)
            if form.is_valid():
                reason = form.cleaned_data["rejection_reason"]
                count = 0
                for doc in pending:
                    review_identity_document(
                        document=doc,
                        reviewer=request.user,
                        action="reject",
                        rejection_reason=reason,
                        request=request,
                    )
                    count += 1
                self.message_user(request, f"Rejected {count} identity document(s).")
                return HttpResponseRedirect(request.get_full_path())
        else:
            form = RejectIdentityDocumentForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Reject selected identity documents",
            "opts": self.model._meta,
            "form": form,
            "documents": pending,
            "pending_count": pending.count(),
            "skipped_count": queryset.count() - pending.count(),
            "queryset": queryset,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(
            request,
            "admin/users/reject_identity_documents.html",
            context,
        )

    def get_queryset(self, request):
        # select_related avoids an N+1 query per row for user/document_type/status.
        return (
            super()
            .get_queryset(request)
            .select_related("user", "document_type", "status")
        )

    @admin.display(description="Document")
    def document(self, obj: IdentityDocument) -> str:
        """Size only. Never dump the bytes into a page element or a list column."""
        data = obj.document_data
        size = len(bytes(data)) if data else 0
        return f"{size:,} bytes"

    @admin.display(description="Download Document")
    def download_link(self, obj: IdentityDocument):
        if not obj or not obj.pk or not obj.document_data:
            return "No document uploaded"
        url = reverse("identity-document-download", args=[obj.pk])
        size = len(bytes(obj.document_data))
        size_str = f"{size:,} bytes"
        return format_html(
            '<a href="{}" target="_blank">Download Document ({})</a>',
            url,
            size_str,
        )


admin.site.register(IdentityDocumentType, IdentityDocumentTypeAdmin)
admin.site.register(IdentityDocumentStatus, IdentityDocumentStatusAdmin)
