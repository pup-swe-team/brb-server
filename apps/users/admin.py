from django.contrib import admin

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
    Administrator-only view of submitted identity documents (FR3).

    This is the *only* surface that may expose the document itself. The mobile
    API deliberately omits `document_data` from every response, so a reviewer has
    to come here to see what was actually uploaded.

    Note for whoever picks up CP-107: this admin is not yet the audited,
    encrypted-at-rest document store the ticket asks for. Access is not yet logged
    to `AdminAccessLog`, and the bytes are not application-level encrypted.
    """

    # `document_data` is intentionally absent from list_display: listing a 5MB
    # blob per row would make the changelist unusable.
    list_display = (
        "id",
        "user",
        "document_type",
        "id_number",
        "status",
        "has_profile_mismatch",
        "submitted_at",
    )
    list_filter = ("status", "document_type", "has_profile_mismatch", "submitted_at")
    search_fields = ("id_number", "user__email", "user__full_name", "name_on_document")
    readonly_fields = (
        "user",
        "document_type",
        "id_number",
        "document_data",
        "status",
        "name_on_document",
        "has_profile_mismatch",
        "consent_given",
        "consented_at",
        "submitted_at",
    )
    date_hierarchy = "submitted_at"

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


admin.site.register(IdentityDocumentType, IdentityDocumentTypeAdmin)
admin.site.register(IdentityDocumentStatus, IdentityDocumentStatusAdmin)
