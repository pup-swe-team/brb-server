from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.audit.services import log_admin_document_access

from .models import IdentityDocument, IdentityDocumentStatus, IdentityDocumentType


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
    actions = ("approve_selected_documents",)

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
