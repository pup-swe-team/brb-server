"""Unified Admin review queue aggregation & action persistence (CP-1103).

Aggregates the three core moderation backlogs into one normalized interface:
  1. Verification (`IdentityDocument`)
  2. Reports (`UserReport`, `ListingReport`, `ReviewReport`, `MessageReport`)
  3. Unreturned Cases (`UnreturnedCase`)

All state mutations delegate to each domain's canonical service function so
notifications, emails, status overrides, and audit logs stay a single code path.
"""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, ValidationError

from apps.orders.constants import (
    CLOSING_UNRETURNED_CASE_STATUSES,
    UNRETURNED_CASE_STATUS_ESCALATED,
    UNRETURNED_CASE_STATUS_OPEN,
)
from apps.orders.models import UnreturnedCase
from apps.orders.selectors import list_unreturned_cases
from apps.orders.services import close_unreturned_case, escalate_unreturned_case
from apps.reports.constants import (
    ALL_REPORT_TARGETS,
    REPORT_STATUS_OPEN,
    REPORT_STATUS_RESOLVED,
)
from apps.reports.models import (
    ListingReport,
    MessageReport,
    ReviewReport,
    UserReport,
)
from apps.reports.serializers import serialize_report
from apps.reports.services import list_reports, resolve_report

from .constants import (
    IDENTITY_DOCUMENT_STATUS_APPROVED,
    IDENTITY_DOCUMENT_STATUS_PENDING,
    IDENTITY_DOCUMENT_STATUS_REJECTED,
)
from .models import IdentityDocument
from .services import review_identity_document

QUEUE_TYPE_VERIFICATION = "verification"
QUEUE_TYPE_REPORT = "report"
QUEUE_TYPE_REPORTS_PLURAL = "reports"
QUEUE_TYPE_UNRETURNED_CASE = "unreturned_case"
QUEUE_TYPE_UNRETURNED_CASES_PLURAL = "unreturned_cases"


class VerificationAlreadyReviewedError(APIException):
    """Raised when an Admin tries to approve/reject an already-reviewed ID document."""

    status_code = 409
    default_detail = "This identity document has already been reviewed."
    default_code = "verification_already_reviewed"


def _serialize_verification_item(doc: IdentityDocument) -> dict[str, Any]:
    return {
        "id": doc.pk,
        "user_id": doc.user_id,
        "user_name": doc.user.full_name or doc.user.email,
        "user_email": doc.user.email,
        "affiliation": doc.user.affiliation,
        "document_type": doc.document_type.name,
        "id_number": doc.id_number,
        "name_on_document": doc.name_on_document,
        "has_profile_mismatch": doc.has_profile_mismatch,
        "status": doc.status.name,
        "rejection_reason": doc.rejection_reason or "",
        "reviewed_by_id": doc.reviewed_by_id,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None,
    }


def list_admin_verifications(
    *,
    status_filter: str = IDENTITY_DOCUMENT_STATUS_PENDING,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return Admin-facing list of IdentityDocument submissions (CP-1103)."""
    normalized = (status_filter or IDENTITY_DOCUMENT_STATUS_PENDING).strip().lower()
    if normalized not in (
        IDENTITY_DOCUMENT_STATUS_PENDING,
        IDENTITY_DOCUMENT_STATUS_APPROVED,
        IDENTITY_DOCUMENT_STATUS_REJECTED,
        "all",
    ):
        raise ValidationError(
            {
                "status": (
                    f"Invalid verification status '{status_filter}'. Must be one of: "
                    "pending, approved, rejected, all."
                )
            }
        )

    qs = (
        IdentityDocument.objects.select_related(
            "user", "document_type", "status", "reviewed_by"
        )
        .defer("document_data")
        .order_by("-submitted_at", "-pk")
    )
    if normalized != "all":
        qs = qs.filter(status__name=normalized)

    return [_serialize_verification_item(doc) for doc in qs[:limit]]


def _open_queue_counts() -> dict[str, int]:
    verification_open = IdentityDocument.objects.filter(
        status__name=IDENTITY_DOCUMENT_STATUS_PENDING
    ).count()
    reports_open = (
        UserReport.objects.filter(status=REPORT_STATUS_OPEN).count()
        + ListingReport.objects.filter(status=REPORT_STATUS_OPEN).count()
        + ReviewReport.objects.filter(status=REPORT_STATUS_OPEN).count()
        + MessageReport.objects.filter(status=REPORT_STATUS_OPEN).count()
    )
    unreturned_open = UnreturnedCase.objects.filter(
        status__name__in=(
            UNRETURNED_CASE_STATUS_OPEN,
            UNRETURNED_CASE_STATUS_ESCALATED,
        )
    ).count()
    return {
        "verification": verification_open,
        "reports": reports_open,
        "unreturned_cases": unreturned_open,
        "total_open": verification_open + reports_open + unreturned_open,
    }


def _normalize_verification_queue_item(doc: IdentityDocument) -> dict[str, Any]:
    is_pending = doc.status.name == IDENTITY_DOCUMENT_STATUS_PENDING
    return {
        "queue_type": QUEUE_TYPE_VERIFICATION,
        "sub_type": doc.document_type.name,
        "id": doc.pk,
        "status": doc.status.name,
        "title": f"Identity Verification — {doc.user.full_name or doc.user.email}",
        "summary": (
            f"{doc.document_type.name.upper()} ({doc.id_number})"
            + (" · Profile mismatch" if doc.has_profile_mismatch else "")
        ),
        "subject_user_id": doc.user_id,
        "subject_user_name": doc.user.full_name or doc.user.email,
        "submitted_at": doc.submitted_at.isoformat() if doc.submitted_at else None,
        "allowed_actions": ["approve", "reject"] if is_pending else [],
        "metadata": _serialize_verification_item(doc),
        "_sort_ts": doc.submitted_at,
    }


def _normalize_report_queue_item(rep: dict[str, Any]) -> dict[str, Any]:
    is_open = rep["status"] == REPORT_STATUS_OPEN
    return {
        "queue_type": QUEUE_TYPE_REPORT,
        "sub_type": rep["report_type"],
        "id": rep["id"],
        "status": rep["status"],
        "title": f"{rep['report_type'].title()} Report #{rep['id']} — {rep['target_display']}",
        "summary": f"{rep['category']}: {rep['description']}",
        "subject_user_id": rep["subject_user_id"],
        "subject_user_name": rep["subject_user_name"],
        "submitted_at": rep["created_at"],
        "allowed_actions": ["resolve"] if is_open else [],
        "metadata": rep,
        "_sort_ts": rep["created_at"] or "",
    }


def _normalize_unreturned_queue_item(case: UnreturnedCase) -> dict[str, Any]:
    is_open = case.status.name in (
        UNRETURNED_CASE_STATUS_OPEN,
        UNRETURNED_CASE_STATUS_ESCALATED,
    )
    return {
        "queue_type": QUEUE_TYPE_UNRETURNED_CASE,
        "sub_type": "unreturned_case",
        "id": case.pk,
        "status": case.status.name,
        "title": f"Unreturned Case #{case.pk} — {case.order.listing.title}",
        "summary": (
            f"Order #{case.order_id} · Borrower: {case.order.borrower.full_name}"
        ),
        "subject_user_id": case.order.borrower_id,
        "subject_user_name": case.order.borrower.full_name,
        "submitted_at": case.created_at.isoformat() if case.created_at else None,
        "allowed_actions": ["escalate", "close"] if is_open else [],
        "metadata": {
            "id": case.pk,
            "order_id": case.order_id,
            "order_status": case.order.status.name,
            "listing_id": case.order.listing_id,
            "listing_title": case.order.listing.title,
            "borrower_id": case.order.borrower_id,
            "borrower_name": case.order.borrower.full_name,
            "lender_id": case.order.listing.lender_id,
            "lender_name": case.order.listing.lender.full_name,
            "status": case.status.name,
            "escalated_at": (
                case.escalated_at.isoformat() if case.escalated_at else None
            ),
            "resolution_notes": case.resolution_notes or "",
        },
        "_sort_ts": case.created_at,
    }


def get_admin_review_queues(
    *,
    queue_type: str = "all",
    status_filter: str = "open",
    limit_per_queue: int = 100,
) -> dict[str, Any]:
    """
    Aggregate Admin review queues across Verification, Reports, and Unreturned Cases (CP-1103).
    """
    normalized_type = (queue_type or "all").strip().lower()
    valid_types = (
        "all",
        QUEUE_TYPE_VERIFICATION,
        "verifications",
        QUEUE_TYPE_REPORT,
        QUEUE_TYPE_REPORTS_PLURAL,
        QUEUE_TYPE_UNRETURNED_CASE,
        QUEUE_TYPE_UNRETURNED_CASES_PLURAL,
    )
    if normalized_type not in valid_types:
        raise ValidationError(
            {
                "type": (
                    f"Invalid queue type '{queue_type}'. Must be one of: "
                    "all, verification, reports, unreturned_cases."
                )
            }
        )

    normalized_status = (status_filter or "open").strip().lower()
    if normalized_status not in ("open", "closed", "all"):
        raise ValidationError(
            {
                "status": (
                    f"Invalid status filter '{status_filter}'. Must be one of: "
                    "open, closed, all."
                )
            }
        )

    include_verification = normalized_type in (
        "all",
        QUEUE_TYPE_VERIFICATION,
        "verifications",
    )
    include_reports = normalized_type in (
        "all",
        QUEUE_TYPE_REPORT,
        QUEUE_TYPE_REPORTS_PLURAL,
    )
    include_unreturned = normalized_type in (
        "all",
        QUEUE_TYPE_UNRETURNED_CASE,
        QUEUE_TYPE_UNRETURNED_CASES_PLURAL,
    )

    items: list[dict[str, Any]] = []

    if include_verification:
        v_qs = (
            IdentityDocument.objects.select_related(
                "user", "document_type", "status", "reviewed_by"
            )
            .defer("document_data")
            .order_by("-submitted_at", "-pk")
        )
        if normalized_status == "open":
            v_qs = v_qs.filter(status__name=IDENTITY_DOCUMENT_STATUS_PENDING)
        elif normalized_status == "closed":
            v_qs = v_qs.filter(
                status__name__in=(
                    IDENTITY_DOCUMENT_STATUS_APPROVED,
                    IDENTITY_DOCUMENT_STATUS_REJECTED,
                )
            )
        for doc in v_qs[:limit_per_queue]:
            items.append(_normalize_verification_queue_item(doc))

    if include_reports:
        rep_status = (
            REPORT_STATUS_OPEN
            if normalized_status == "open"
            else REPORT_STATUS_RESOLVED
            if normalized_status == "closed"
            else "all"
        )
        for rep in list_reports(
            report_type="all",
            status_filter=rep_status,
            limit_per_type=limit_per_queue,
        ):
            items.append(_normalize_report_queue_item(rep))

    if include_unreturned:
        u_qs = list_unreturned_cases()
        if normalized_status == "open":
            u_qs = u_qs.filter(
                status__name__in=(
                    UNRETURNED_CASE_STATUS_OPEN,
                    UNRETURNED_CASE_STATUS_ESCALATED,
                )
            )
        elif normalized_status == "closed":
            u_qs = u_qs.filter(status__name__in=CLOSING_UNRETURNED_CASE_STATUSES)
        for case in u_qs[:limit_per_queue]:
            items.append(_normalize_unreturned_queue_item(case))

    # Sort all items newest-first using ISO timestamp strings
    items.sort(key=lambda item: item["submitted_at"] or "", reverse=True)
    for item in items:
        item.pop("_sort_ts", None)

    return {
        "counts": _open_queue_counts(),
        "filter": {
            "type": normalized_type,
            "status": normalized_status,
        },
        "items": items,
    }


def perform_review_queue_action(
    *,
    queue_type: str,
    item_id: int,
    admin: Any,
    action: str,
    data: dict[str, Any],
    evidence_files: list | None = None,
    request: Any = None,
) -> dict[str, Any]:
    """
    Persist an Admin approve/reject/resolve/escalate/close decision for any queue type (CP-1103).
    """
    normalized_queue = (queue_type or "").strip().lower()
    normalized_action = (action or "").strip().lower()

    # 1. Verification Queue (IdentityDocument)
    if normalized_queue in (QUEUE_TYPE_VERIFICATION, "verifications"):
        if normalized_action not in ("approve", "reject"):
            raise ValidationError(
                {"action": "Verification action must be 'approve' or 'reject'."}
            )
        document = get_object_or_404(
            IdentityDocument.objects.select_related(
                "user", "document_type", "status", "reviewed_by"
            ),
            pk=item_id,
        )
        if document.status.name != IDENTITY_DOCUMENT_STATUS_PENDING:
            raise VerificationAlreadyReviewedError()

        rejection_reason = (
            data.get("rejection_reason") or data.get("reason") or ""
        ).strip()
        if normalized_action == "reject" and not rejection_reason:
            raise ValidationError(
                {"rejection_reason": "A rejection reason is required when rejecting."}
            )

        updated_doc = review_identity_document(
            document=document,
            reviewer=admin,
            action=normalized_action,
            rejection_reason=rejection_reason,
            request=request,
        )
        return {
            "queue_type": QUEUE_TYPE_VERIFICATION,
            "action": normalized_action,
            "item": _serialize_verification_item(updated_doc),
        }

    # 2. Reports Queue (User / Listing / Review / Message)
    report_sub_type: str | None = None
    if normalized_queue in (QUEUE_TYPE_REPORT, QUEUE_TYPE_REPORTS_PLURAL):
        report_sub_type = (
            (data.get("report_type") or data.get("sub_type") or "").strip().lower()
        )
    elif normalized_queue.startswith("report_"):
        report_sub_type = normalized_queue.removeprefix("report_")

    if report_sub_type is not None:
        if report_sub_type not in ALL_REPORT_TARGETS:
            raise ValidationError(
                {
                    "report_type": (
                        "Report actions require report_type to be one of: "
                        f"{', '.join(ALL_REPORT_TARGETS)}."
                    )
                }
            )
        if normalized_action not in ("resolve", "dismiss"):
            raise ValidationError(
                {"action": "Report action must be 'resolve' or 'dismiss'."}
            )
        notes = (data.get("resolution_notes") or data.get("notes") or "").strip()
        if normalized_action == "dismiss" and not notes:
            notes = "Dismissed by administrator."
        updated_report = resolve_report(
            report_type=report_sub_type,
            report_id=item_id,
            admin=admin,
            resolution_notes=notes,
        )
        return {
            "queue_type": QUEUE_TYPE_REPORT,
            "sub_type": report_sub_type,
            "action": normalized_action,
            "item": serialize_report(updated_report),
        }

    # 3. Unreturned Cases Queue
    if normalized_queue in (
        QUEUE_TYPE_UNRETURNED_CASE,
        QUEUE_TYPE_UNRETURNED_CASES_PLURAL,
    ):
        notes = (data.get("resolution_notes") or data.get("notes") or "").strip()
        if normalized_action == "escalate":
            updated_case = escalate_unreturned_case(
                case_id=item_id,
                admin=admin,
                resolution_notes=notes,
                evidence_files=evidence_files,
            )
        elif normalized_action in ("close", "returned", "unresolved"):
            close_status = (
                normalized_action
                if normalized_action in CLOSING_UNRETURNED_CASE_STATUSES
                else (data.get("status") or data.get("outcome") or "").strip().lower()
            )
            updated_case = close_unreturned_case(
                case_id=item_id,
                admin=admin,
                close_status=close_status,
                resolution_notes=notes,
            )
        else:
            raise ValidationError(
                {
                    "action": (
                        "Unreturned case action must be 'escalate', 'close', "
                        "'returned', or 'unresolved'."
                    )
                }
            )
        updated_case = UnreturnedCase.objects.select_related(
            "order",
            "order__listing",
            "order__listing__lender",
            "order__borrower",
            "order__status",
            "status",
            "escalated_by",
        ).get(pk=updated_case.pk)
        item_payload = _normalize_unreturned_queue_item(updated_case)
        item_payload.pop("_sort_ts", None)
        return {
            "queue_type": QUEUE_TYPE_UNRETURNED_CASE,
            "action": normalized_action,
            "item": item_payload,
        }

    raise ValidationError(
        {
            "queue_type": (
                f"Invalid queue_type '{queue_type}'. Must be one of: "
                "verification, report, report_user, report_listing, "
                "report_review, report_message, unreturned_case."
            )
        }
    )
