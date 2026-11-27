"""Selectors and read-queries for Admin UnreturnedCase and Dispute dossiers (CP-506, CP-903)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.audit.services import log_admin_document_access
from apps.chat.models import Conversation
from apps.codes.models import AuthCode
from apps.reports.models import ListingReport, UserReport
from apps.users.models import IdentityDocument, User

from .models import Dispute, DisputeEvidence, UnreturnedCase


def list_unreturned_cases(
    *, status_filter: str | None = None
) -> QuerySet[UnreturnedCase]:
    """Return all UnreturnedCase rows ordered newest-first, optionally filtered by status."""
    qs = UnreturnedCase.objects.select_related(
        "order",
        "order__listing",
        "order__listing__lender",
        "order__borrower",
        "order__status",
        "status",
        "escalated_by",
    ).order_by("-created_at", "-pk")

    if status_filter:
        qs = qs.filter(status__name=status_filter.strip().lower())
    return qs


def _serialize_party_contact_and_identity(
    user: User,
    *,
    admin: User,
    request: Any = None,
    include_identity_documents: bool = True,
) -> dict[str, Any]:
    """
    Build contact and identity verification metadata for an order participant (CP-506).
    Never exposes raw `document_data` bytes; logs `AdminAccessLog(action='contact_release')`
    for every linked identity document per FR3, FR14, and CP-107.
    """
    address_parts = [
        part
        for part in (
            (user.street_address or "").strip(),
            user.municipality.name if user.municipality_id else "",
            user.province.name if user.province_id else "",
        )
        if part
    ]

    identity_docs_payload: list[dict[str, Any]] = []
    if include_identity_documents:
        documents = (
            IdentityDocument.objects.filter(user=user)
            .select_related("document_type", "status", "reviewed_by")
            .order_by("-submitted_at", "-pk")
        )
        for doc in documents:
            log_admin_document_access(
                document=doc,
                admin=admin,
                action="contact_release",
                request=request,
            )
            identity_docs_payload.append(
                {
                    "id": doc.pk,
                    "document_type": doc.document_type.name,
                    "id_number": doc.id_number,
                    "name_on_document": doc.name_on_document,
                    "status": doc.status.name,
                    "has_profile_mismatch": doc.has_profile_mismatch,
                    "submitted_at": doc.submitted_at,
                    "reviewed_at": doc.reviewed_at,
                    "download_url": reverse(
                        "identity-document-download", kwargs={"pk": doc.pk}
                    ),
                }
            )

    return {
        "id": user.pk,
        "full_name": user.full_name,
        "email": user.email,
        "contact_number": user.contact_number,
        "affiliation": user.affiliation,
        "account_status": user.account_status,
        "lender_status": user.lender_status,
        "street_address": user.street_address,
        "municipality": user.municipality.name if user.municipality_id else None,
        "province": user.province.name if user.province_id else None,
        "formatted_address": ", ".join(address_parts) if address_parts else "",
        "identity_documents": identity_docs_payload,
    }


def get_unreturned_case_dossier(
    *,
    case_id: int,
    admin: User,
    request: Any = None,
) -> dict[str, Any]:
    """
    Assemble the complete Admin review case dossier for an UnreturnedCase (CP-506),
    linking identity, contact, order, chat history, authentication codes/attempts,
    and escalation evidence.
    """
    case = get_object_or_404(
        UnreturnedCase.objects.select_related(
            "order",
            "order__listing",
            "order__listing__category",
            "order__listing__pickup_location",
            "order__listing__lender",
            "order__listing__lender__municipality",
            "order__listing__lender__province",
            "order__borrower",
            "order__borrower__municipality",
            "order__borrower__province",
            "order__status",
            "status",
            "escalated_by",
        ),
        pk=case_id,
    )
    order = case.order
    borrower = order.borrower
    lender = order.listing.lender

    # 1. Identity & Contact data (logs AdminAccessLog for borrower & lender ID docs)
    borrower_data = _serialize_party_contact_and_identity(
        borrower, admin=admin, request=request, include_identity_documents=True
    )
    lender_data = _serialize_party_contact_and_identity(
        lender, admin=admin, request=request, include_identity_documents=True
    )

    # 2. Order & status override data
    overrides_data = [
        {
            "id": ov.pk,
            "admin_id": ov.admin_id,
            "admin_name": ov.admin.full_name,
            "previous_status": ov.previous_status,
            "new_status": ov.new_status,
            "reason": ov.reason,
            "overridden_at": ov.overridden_at,
        }
        for ov in order.status_overrides.select_related("admin").order_by(
            "overridden_at", "pk"
        )
    ]

    order_data = {
        "id": order.pk,
        "listing": {
            "id": order.listing_id,
            "title": order.listing.title,
            "category": order.listing.category.name,
            "condition": order.listing.condition,
            "pickup_location": order.listing.pickup_location.name,
        },
        "start_date": order.start_date,
        "end_date": order.end_date,
        "status": order.status.name,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "status_overrides": overrides_data,
    }

    # 3. Chat conversations & messages linked to the order (or between parties for this listing)
    conversations = (
        Conversation.objects.filter(
            Q(order=order)
            | (
                Q(listing=order.listing)
                & (
                    Q(user_a=borrower, user_b=lender)
                    | Q(user_a=lender, user_b=borrower)
                )
            )
        )
        .prefetch_related("messages__sender")
        .order_by("created_at", "pk")
        .distinct()
    )
    chat_data = [
        {
            "conversation_id": conv.conversation_id,
            "order_id": conv.order_id,
            "listing_id": conv.listing_id,
            "is_blocked": conv.is_blocked,
            "messages": [
                {
                    "id": msg.pk,
                    "sender_id": msg.sender_id,
                    "sender_name": msg.sender.full_name,
                    "content": msg.content,
                    "sent_at": msg.sent_at,
                    "read_at": msg.read_at,
                }
                for msg in conv.messages.all().order_by("sent_at", "pk")
            ],
        }
        for conv in conversations
    ]

    # 4. Authentication codes & attempts history
    auth_codes = (
        AuthCode.objects.filter(order=order)
        .select_related("code_type", "auth_status")
        .prefetch_related("attempts__attempted_by")
        .order_by("generated_at", "pk")
    )
    codes_data = [
        {
            "id": code.pk,
            "code_type": code.code_type.name,
            "code_value": code.code_value,
            "auth_status": code.auth_status.name,
            "generated_at": code.generated_at,
            "expires_at": code.expires_at,
            "used_at": code.used_at,
            "attempts": [
                {
                    "id": att.pk,
                    "attempted_by_id": att.attempted_by_id,
                    "attempted_by_name": att.attempted_by.full_name,
                    "was_successful": att.was_successful,
                    "attempted_at": att.attempted_at,
                }
                for att in code.attempts.all().order_by("attempted_at", "pk")
            ],
        }
        for code in auth_codes
    ]

    # 5. Attached evidence files (from any Dispute/Escalation on this order)
    evidences = (
        DisputeEvidence.objects.filter(dispute__order=order)
        .select_related("file_type", "submitted_by", "dispute")
        .order_by("uploaded_at", "pk")
    )
    evidence_data = [
        {
            "id": ev.pk,
            "dispute_id": ev.dispute_id,
            "file_url": ev.file_reference.url if ev.file_reference else None,
            "file_type": ev.file_type.name,
            "submitted_by_id": ev.submitted_by_id,
            "submitted_by_name": ev.submitted_by.full_name,
            "uploaded_at": ev.uploaded_at,
        }
        for ev in evidences
    ]

    return {
        "id": case.pk,
        "status": case.status.name,
        "escalated_at": case.escalated_at,
        "escalated_by_id": case.escalated_by_id,
        "escalated_by_name": case.escalated_by.full_name if case.escalated_by else None,
        "resolution_notes": case.resolution_notes,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "order": order_data,
        "borrower": borrower_data,
        "lender": lender_data,
        "chat": chat_data,
        "codes": codes_data,
        "evidences": evidence_data,
    }


def list_disputes(*, status_filter: str | None = None) -> QuerySet[Dispute]:
    """Return all Dispute rows ordered newest-first, optionally filtered by status (CP-903)."""
    qs = (
        Dispute.objects.select_related(
            "order",
            "order__listing",
            "order__listing__lender",
            "order__borrower",
            "order__status",
            "raised_by",
            "resolved_by",
        )
        .prefetch_related(
            "evidences", "evidences__file_type", "evidences__submitted_by"
        )
        .order_by("-created_at", "-pk")
    )
    if status_filter:
        qs = qs.filter(status=status_filter.strip().lower())
    return qs


def get_dispute_dossier(
    *,
    dispute_id: int,
    admin: User,
    request: Any = None,
) -> dict[str, Any]:
    """
    Assemble the complete Admin review dossier for a damage/missing-item Dispute (CP-903),
    linking order, photos/videos, linked reports, chat history, auth code attempts,
    and audited contact/identity metadata.
    """
    dispute = get_object_or_404(
        Dispute.objects.select_related(
            "order",
            "order__listing",
            "order__listing__category",
            "order__listing__pickup_location",
            "order__listing__lender",
            "order__listing__lender__municipality",
            "order__listing__lender__province",
            "order__borrower",
            "order__borrower__municipality",
            "order__borrower__province",
            "order__status",
            "raised_by",
            "resolved_by",
        ).prefetch_related(
            "evidences", "evidences__file_type", "evidences__submitted_by"
        ),
        pk=dispute_id,
    )
    order = dispute.order
    listing = order.listing
    borrower = order.borrower
    lender = listing.lender

    # 1. Identity & Contact data (logs AdminAccessLog(action='contact_release') per FR3/FR14)
    borrower_data = _serialize_party_contact_and_identity(
        borrower, admin=admin, request=request, include_identity_documents=True
    )
    lender_data = _serialize_party_contact_and_identity(
        lender, admin=admin, request=request, include_identity_documents=True
    )

    # 2. Order & status override history
    overrides_data = [
        {
            "id": ov.pk,
            "admin_id": ov.admin_id,
            "admin_name": ov.admin.full_name,
            "previous_status": ov.previous_status,
            "new_status": ov.new_status,
            "reason": ov.reason,
            "overridden_at": ov.overridden_at.isoformat() if ov.overridden_at else None,
        }
        for ov in order.status_overrides.select_related("admin").order_by(
            "overridden_at", "pk"
        )
    ]

    # 3. Evidence photos/videos
    evidences_data = []
    for ev in dispute.evidences.all().order_by("uploaded_at", "pk"):
        url = ev.file_reference.url if ev.file_reference else ""
        if url and request is not None and not url.startswith("http"):
            url = request.build_absolute_uri(url)
        evidences_data.append(
            {
                "id": ev.pk,
                "file_url": url,
                "file_type": ev.file_type.name if ev.file_type else "photo",
                "submitted_by_id": ev.submitted_by_id,
                "submitted_by_name": ev.submitted_by.full_name,
                "uploaded_at": ev.uploaded_at.isoformat(),
            }
        )

    # 4. Linked reports (UserReports tied to order/parties + ListingReports on listing)
    user_reports = (
        UserReport.objects.filter(
            Q(order=order)
            | (
                Q(reporter=borrower, target_user=lender)
                | Q(reporter=lender, target_user=borrower)
            )
        )
        .select_related("reporter", "target_user", "category")
        .order_by("-created_at", "-pk")
    )
    listing_reports = (
        ListingReport.objects.filter(target_listing=listing)
        .select_related("reporter", "category")
        .order_by("-created_at", "-pk")
    )
    reports_data = [
        {
            "id": r.pk,
            "type": "user",
            "order_id": r.order_id,
            "reporter_id": r.reporter_id,
            "reporter_name": r.reporter.full_name,
            "target_id": r.target_user_id,
            "target_name": r.target_user.full_name,
            "category": r.category.name if r.category else "",
            "description": r.description,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in user_reports
    ] + [
        {
            "id": r.pk,
            "type": "listing",
            "order_id": None,
            "reporter_id": r.reporter_id,
            "reporter_name": r.reporter.full_name,
            "target_id": r.target_listing_id,
            "target_name": listing.title,
            "category": r.category.name if r.category else "",
            "description": r.description,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in listing_reports
    ]

    # 5. Linked chat conversations & messages (uses shared CP-703 selector preserving retention info)
    from apps.chat.selectors import get_conversations_for_order_dossier

    chat_data = get_conversations_for_order_dossier(order)

    # 6. Authentication codes & attempts history
    auth_codes = (
        AuthCode.objects.filter(order=order)
        .select_related("code_type", "auth_status")
        .prefetch_related("attempts__attempted_by")
        .order_by("generated_at", "pk")
    )
    codes_data = [
        {
            "id": code.pk,
            "code_type": code.code_type.name,
            "code_value": code.code_value,
            "auth_status": code.auth_status.name,
            "generated_at": code.generated_at.isoformat(),
            "expires_at": code.expires_at.isoformat(),
            "used_at": code.used_at.isoformat() if code.used_at else None,
            "attempts": [
                {
                    "id": att.pk,
                    "attempted_by_id": att.attempted_by_id,
                    "attempted_by_name": att.attempted_by.full_name,
                    "was_successful": att.was_successful,
                    "attempted_at": att.attempted_at.isoformat(),
                }
                for att in code.attempts.all().order_by("attempted_at", "pk")
            ],
        }
        for code in auth_codes
    ]

    events = [
        {
            "id": "e1",
            "label": "Dispute reported",
            "date": dispute.created_at.strftime("%Y-%m-%d"),
        }
    ]
    if dispute.borrower_response:
        events.append(
            {
                "id": "e_response",
                "label": "Borrower response submitted",
                "date": dispute.updated_at.strftime("%Y-%m-%d"),
            }
        )
    if dispute.resolution_notes:
        prefix = (
            "Escalated"
            if dispute.status == Dispute.StatusChoices.ESCALATED
            else "Resolution"
        )
        events.append(
            {
                "id": "e2",
                "label": f"{prefix}: {dispute.resolution_notes}",
                "date": dispute.updated_at.strftime("%Y-%m-%d"),
            }
        )

    return {
        "case": {
            "id": dispute.pk,
            "dispute_id": dispute.pk,
            "case_id": f"DISP-{dispute.pk}",
            "order_id": order.pk,
            "type": "damage_dispute",
            "status": dispute.status,
            "description": dispute.description,
            "borrower_response": dispute.borrower_response or "",
            "evidence": [
                {
                    "id": ev["id"],
                    "file": ev["file_url"],
                    "media_type": ev["file_type"],
                    "created_at": ev["uploaded_at"],
                }
                for ev in evidences_data
            ],
            "raised_by_id": dispute.raised_by_id,
            "raised_by_name": dispute.raised_by.full_name,
            "resolved_by_id": dispute.resolved_by_id,
            "resolved_by_name": (
                dispute.resolved_by.full_name if dispute.resolved_by else None
            ),
            "resolution_notes": dispute.resolution_notes or "",
            "notes": dispute.resolution_notes or "",
            "created_at": dispute.created_at.isoformat(),
            "updated_at": dispute.updated_at.isoformat(),
        },
        "order": {
            "id": order.pk,
            "status": order.status.name,
            "start_date": str(order.start_date),
            "end_date": str(order.end_date),
            "pickup_location": getattr(listing.pickup_location, "name", ""),
            "completed_at": order.completed_at.isoformat()
            if order.completed_at
            else None,
            "status_overrides": overrides_data,
        },
        "listing": {
            "id": listing.pk,
            "title": listing.title,
            "price_per_day": (
                f"{listing.rate_per_day:.2f}"
                if listing.rate_per_day is not None
                else "0.00"
            ),
            "category": getattr(listing.category, "name", ""),
            "condition": listing.condition,
            "pickup_location": getattr(listing.pickup_location, "name", ""),
        },
        "borrower": borrower_data,
        "lender": lender_data,
        "evidences": evidences_data,
        "reports": reports_data,
        "chat": chat_data,
        "codes": codes_data,
        "events": events,
    }
