"""
CoPUPAdmin portal (BE-BUG-0006).

Server-rendered pages for the administrator verification workflow (CP-106),
matching the Figma "CoPUPAdmin" screens 76 (sign-in), 77 (dashboard),
82 (verification queue), 83 (verification review) and 84 (reject overlay).

The portal is Django-rendered on purpose: the identity review flow already
lives on the server (Django Admin actions + the /api/v1/identity/ endpoints),
and these pages reuse the same service functions so the decisions, in-app
notifications, emails and audit trail stay a single code path.

Authority is Django's `is_staff` flag, not `affiliation` (D-03). Only staff
accounts may sign in here -- anyone else is rejected by the login view and
every staff-gated page logs them out.
"""

import functools
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Count, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import DateFormat
from django.views.decorators.http import require_POST

from apps.audit.services import log_admin_document_access
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.orders.models import Order
from apps.reports.models import (
    ListingReport,
    MessageReport,
    ReviewReport,
    UserReport,
)

from .constants import (
    IDENTITY_DOCUMENT_STATUS_PENDING,
    IDENTITY_DOCUMENT_TYPE_PUP_ID,
    PUP_ID_NUMBER_REGEX,
)
from .encryption import decrypt_document_data, detect_document_content_type
from .models import IdentityDocument, IdentityDocumentStatus, User
from .services import review_identity_document

# Display labels for the two accepted document types (CP-105 lookup rows).
IDENTITY_DOCUMENT_TYPE_LABELS = {
    "pup_id": "PUP ID",
    "government_id": "Government-issued ID",
}

# The order-status rows the dashboard chart highlights, in the design's order.
DASHBOARD_ORDER_STATUSES = (
    "requested",
    "confirmed",
    "active",
    "overdue",
    "returned",
    "completed",
    "disputed",
    "unreturned",
)


def document_type_label(name: str) -> str:
    """Human label for a document type lookup row, e.g. pup_id -> PUP ID."""
    return IDENTITY_DOCUMENT_TYPE_LABELS.get(name, name.replace("_", " ").title())


def initials(full_name: str) -> str:
    """Avatar initials from a full name: 'Danielo Kim R. Ang' -> 'DA'."""
    parts = [part for part in (full_name or "").split() if part]
    if not parts:
        return "?"
    first = parts[0][0]
    last = parts[-1][0] if len(parts) > 1 else ""
    return (first + last).upper()


def format_user_address(user: User) -> str:
    """Street, municipality and province from a user's profile, joined nicely."""
    parts = [user.street_address.strip()]
    if user.municipality_id:
        parts.append(user.municipality.name)
    if user.province_id:
        parts.append(user.province.name)
    return ", ".join(part for part in parts if part) or "\u2014"


def day_or_time_label(timestamp) -> str:
    """'h:mm AM/PM' for today, 'Jan. 30' otherwise -- mirrors the design."""
    local = timezone.localtime(timestamp)
    if local.date() == timezone.localdate():
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        return f"{hour}:{local.minute:02d} {ampm}"
    return DateFormat(local).format("M. j, Y")


def staff_login_required(view):
    """Gate a portal page: staff only, everyone else bounced to the sign-in."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            next_url = request.path
            return redirect(f"{reverse('portal-login')}?next={next_url}")
        if not request.user.is_staff:
            auth_logout(request)
            return redirect(reverse("portal-login"))
        return view(request, *args, **kwargs)

    return wrapper


def _identity_document_tab_counts() -> dict[str, int]:
    counts = IdentityDocument.objects.values("status__name").annotate(total=Count("id"))
    totals = {"pending": 0, "approved": 0, "rejected": 0}
    for row in counts:
        totals[row["status__name"]] = row["total"]
    return totals


def _open_reports_count() -> int:
    return (
        ListingReport.objects.filter(status="open").count()
        + UserReport.objects.filter(status="open").count()
        + ReviewReport.objects.filter(status="open").count()
        + MessageReport.objects.filter(status="open").count()
    )


def _recent_activity() -> list[dict[str, str]]:
    """A small, truthful activity feed drawn from the tables that exist."""
    events: list[tuple] = []

    for document in IdentityDocument.objects.select_related(
        "user", "document_type", "status"
    ).filter(status__name__in=("approved", "rejected"), reviewed_at__isnull=False)[:5]:
        events.append(
            (
                document.reviewed_at,
                "Verification",
                f"Identity document {document.status.name}",
                f"{document.user.full_name} \u00b7 {document_type_label(document.document_type.name)}",
            )
        )

    for document in IdentityDocument.objects.select_related(
        "user", "document_type"
    ).filter(status__name=IDENTITY_DOCUMENT_STATUS_PENDING)[:5]:
        events.append(
            (
                document.submitted_at,
                "Verification",
                "Verification submitted",
                f"{document.user.full_name} \u00b7 {document_type_label(document.document_type.name)}",
            )
        )

    for report in UserReport.objects.select_related("target_user").order_by(
        "-created_at"
    )[:3]:
        events.append(
            (report.created_at, "Report", "New report", report.target_user.full_name)
        )
    for report in ListingReport.objects.select_related("target_listing").order_by(
        "-created_at"
    )[:3]:
        events.append(
            (
                report.created_at,
                "Report",
                "New report",
                f"On listing \u00ab{report.target_listing.title}\u00bb",
            )
        )

    for order in Order.objects.select_related("listing", "borrower").order_by(
        "-created_at"
    )[:4]:
        events.append(
            (
                order.created_at,
                "Order",
                "New order placed",
                f"{order.listing.title} \u00b7 {order.borrower.full_name}",
            )
        )

    events.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "time": day_or_time_label(stamp),
            "kind": kind,
            "title": title,
            "detail": detail,
        }
        for stamp, kind, title, detail in events[:6]
    ]


class AdminPortalLoginView:
    """
    Admin sign-in (screen 76). Rejects any account that is not staff, so the
    portal stays closed to ordinary members.
    """

    template_name = "admin_portal/login.html"

    def __call__(self, request):
        if request.method == "POST":
            form = AuthenticationForm(request, data=request.POST)
            if form.is_valid():
                user = form.get_user()
                if not user.is_staff:
                    form.add_error(
                        None, "Only administrator accounts can sign in here."
                    )
                else:
                    auth_login(request, user)
                    return redirect(reverse("portal-dashboard"))
        else:
            if request.user.is_authenticated:
                if request.user.is_staff:
                    return redirect(reverse("portal-dashboard"))
                auth_logout(request)
            form = AuthenticationForm(request)

        return render(request, self.template_name, {"form": form})


@require_POST
def portal_logout(request):
    """End the admin session (header chip -> Sign out)."""
    auth_logout(request)
    return redirect(reverse("portal-login"))


@staff_login_required
def dashboard(request):
    """
    Overview page (screen 77): four stat cards, the orders-by-status chart and a
    recent activity feed. Every figure is computed from the real tables; cards
    whose domain has no data yet read zero rather than pretending otherwise.
    """
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    pending_status = IdentityDocumentStatus.objects.get(
        name=IDENTITY_DOCUMENT_STATUS_PENDING
    )
    pending_documents = IdentityDocument.objects.filter(status=pending_status)
    oldest_waiting = pending_documents.aggregate(oldest=Min("submitted_at"))["oldest"]
    pending_days = (now - oldest_waiting).days if oldest_waiting is not None else None

    active_listings_total = 0
    active_status = ListingStatus.objects.filter(name="active").first()
    if active_status is not None:
        active_listings_total = Listing.objects.filter(status=active_status).count()

    orders_by_status = {name: 0 for name in DASHBOARD_ORDER_STATUSES}
    for row in Order.objects.values("status__name").annotate(total=Count("id")):
        if row["status__name"] in orders_by_status:
            orders_by_status[row["status__name"]] = row["total"]
    order_rows = [
        {"name": name, "total": total} for name, total in orders_by_status.items()
    ]
    max_orders = max((row["total"] for row in order_rows), default=0)
    for row in order_rows:
        row["percent"] = round(row["total"] / max_orders * 100) if max_orders else 0

    stats = {
        "total_users": User.objects.count(),
        "new_users_this_month": User.objects.filter(
            created_at__gte=month_start
        ).count(),
        "active_listings": active_listings_total,
        "listings_added_week": Listing.objects.filter(
            created_at__gte=week_start
        ).count(),
        "open_reports": _open_reports_count(),
        "pending_verifications": pending_documents.count(),
        "pending_days": pending_days,
    }

    context = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
        "stats": stats,
        "orders_by_status_rows": order_rows,
        "activity": _recent_activity(),
        "nav_verification_count": stats["pending_verifications"],
        "nav_reports_count": stats["open_reports"],
    }
    return render(request, "admin_portal/dashboard.html", context)


@staff_login_required
def verification_queue(request):
    """
    Verification queue (screen 82): Pending/Approved/Rejected tabs over the
    submitted identity documents, with the design's table columns and footer
    pagination.
    """
    tabs = []
    for name in ("pending", "approved", "rejected"):
        tabs.append(
            {
                "name": name,
                "label": "Pending Review" if name == "pending" else name.title(),
                "count": _identity_document_tab_counts()[name],
            }
        )

    current = request.GET.get("status", "pending")
    if current not in ("pending", "approved", "rejected"):
        current = "pending"

    documents = (
        IdentityDocument.objects.filter(status__name=current)
        .select_related("user", "document_type", "status")
        .order_by("-submitted_at")
    )

    paginator = Paginator(documents, 6)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "Verification Queue",
        "active_nav": "verification",
        "tabs": tabs,
        "current_status": current,
        "page": page,
        "paginator": paginator,
        "start_index": page.start_index() or 0,
        "end_index": page.end_index() or paginator.count,
        "nav_verification_count": tabs[0]["count"],
        "nav_reports_count": _open_reports_count(),
    }
    return render(request, "admin_portal/verification_queue.html", context)


@staff_login_required
def verification_review(request, pk: int):
    """
    Verification review page (screen 83): the submitted document, the
    submitted details, the server-side checks, and the Approve/Reject decision.
    Opening the page is recorded in the audit log, matching the Django Admin
    `change_view` behaviour and the design's notice under the document image.
    """
    document = get_object_or_404(
        IdentityDocument.objects.select_related(
            "user", "document_type", "status", "user__municipality", "user__province"
        ),
        pk=pk,
    )

    log_admin_document_access(
        document=document,
        admin=request.user,
        action="view",
        request=request,
    )

    raw_bytes = decrypt_document_data(document.document_data)
    content_type, extension = detect_document_content_type(raw_bytes)
    is_image = content_type.startswith("image/")

    id_number_in_use = (
        IdentityDocument.objects.filter(id_number__iexact=document.id_number)
        .exclude(user=document.user)
        .exists()
    )

    checks = [
        {
            "label": "No other account uses this ID number",
            "pass": not id_number_in_use,
        },
        {
            "label": "Consent recorded: ID storage",
            "pass": document.consent_given and document.consented_at is not None,
            "detail": (
                DateFormat(timezone.localtime(document.consented_at)).format("M. j, Y")
                if document.consented_at
                else ""
            ),
        },
        {
            "label": "Account email is verified",
            "pass": document.user.is_email_verified,
        },
    ]
    if document.document_type.name == IDENTITY_DOCUMENT_TYPE_PUP_ID:
        checks.insert(
            1,
            {
                "label": "ID number uses the PUP format (20xx-xxxxx-MN-x)",
                "pass": PUP_ID_NUMBER_REGEX.match(document.id_number) is not None,
            },
        )

    details = [
        {
            "label": "Full Name",
            "value": document.user.full_name,
            "note": (
                "Does not match the account name\u2014check carefully."
                if document.has_profile_mismatch
                else "Matches the ID and account name"
            ),
            "ok": not document.has_profile_mismatch,
        },
        {
            "label": "ID Number",
            "value": document.id_number,
            "note": "Compare with the document photo",
        },
        {
            "label": "Address",
            "value": format_user_address(document.user),
            "note": "Compare with the document photo",
        },
    ]

    context = {
        "page_title": "Verification Review",
        "active_nav": "verification",
        "document": document,
        "details": details,
        "checks": checks,
        "is_image": is_image,
        "extension": extension,
        "download_url": reverse("identity-document-download", args=[document.pk]),
        "nav_verification_count": IdentityDocument.objects.filter(
            status__name=IDENTITY_DOCUMENT_STATUS_PENDING
        ).count(),
        "nav_reports_count": _open_reports_count(),
    }
    return render(request, "admin_portal/verification_review.html", context)


@require_POST
@staff_login_required
def verification_review_submit(request, pk: int):
    """
    Approve or reject a pending document (screen 84). Replicates the guard rails
    the API review endpoint already enforces -- pending-only, reject requires a
    reason -- then delegates to `review_identity_document` for the shared
    notification/audit/email side effects. Always redirects (PRG).
    """
    document = get_object_or_404(
        IdentityDocument.objects.select_related("user", "status"), pk=pk
    )

    if document.status.name != IDENTITY_DOCUMENT_STATUS_PENDING:
        messages.error(
            request,
            "This document has already been reviewed.",
        )
        return redirect(reverse("portal-verification-review", args=[document.pk]))

    action = request.POST.get("action")
    if action not in ("approve", "reject"):
        messages.error(request, "Choose approve or reject.")
        return redirect(reverse("portal-verification-review", args=[document.pk]))

    rejection_reason = request.POST.get("rejection_reason", "").strip()
    if action == "reject" and not rejection_reason:
        messages.error(
            request,
            "A reason is required when rejecting a document. "
            f"{document.user.full_name} will see it.",
        )
        return redirect(reverse("portal-verification-review", args=[document.pk]))

    review_identity_document(
        document=document,
        reviewer=request.user,
        action=action,
        rejection_reason=rejection_reason,
        request=request,
    )

    outcome = "approved" if action == "approve" else "rejected"
    messages.success(
        request,
        f"Verification {outcome} for {document.user.full_name}.",
    )
    return redirect(reverse("portal-verification-queue"))


# ---------------------------------------------------------------------------
# CP-1108 -- Pickup-location management (portal mirror of CP-1105)


class PickupLocationPortalForm(forms.Form):
    """
    The CP-1105 rules restated for a server-rendered form: a trimmed, non-blank
    name up to 150 characters and an optional description. The required-error
    wording matches `PickupLocationSerializer.validate_name` so the API and the
    portal say the same thing about the same input.
    """

    name = forms.CharField(
        max_length=150,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "class": "field-input",
                "placeholder": "e.g. PUP Main Library Front Desk",
            }
        ),
        error_messages={"required": "Location name cannot be blank."},
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "Landmark, floor, desk - anything that helps borrowers find it (optional)",
            }
        ),
    )


def _pickup_location_context() -> dict:
    """Shared context for the pickup pages: split lists in the API's order."""
    return {
        "active_nav": "pickup",
        "locations": PickupLocation.objects.filter(deleted_at__isnull=True).order_by(
            "name"
        ),
        "archived": PickupLocation.objects.filter(deleted_at__isnull=False).order_by(
            "name"
        ),
        "nav_verification_count": _identity_document_tab_counts()["pending"],
        "nav_reports_count": _open_reports_count(),
    }


@staff_login_required
def pickup_locations(request):
    """
    Pickup-location management page (CP-1108): active locations with add form,
    removed (soft-deleted) locations with Restore. Create follows PRG like the
    rest of the portal; validation errors re-render the form inline.
    """
    if request.method == "POST":
        form = PickupLocationPortalForm(request.POST)
        if form.is_valid():
            PickupLocation.objects.create(
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"] or None,
            )
            messages.success(
                request,
                f"Pickup location \u201c{form.cleaned_data['name']}\u201d added.",
            )
            return redirect(reverse("portal-pickup-locations"))
    else:
        form = PickupLocationPortalForm()

    context = {
        "page_title": "Pickup Locations",
        "form": form,
        **_pickup_location_context(),
    }
    return render(request, "admin_portal/pickup_locations.html", context)


@staff_login_required
def pickup_location_edit(request, pk: int):
    """Edit one active location (CP-1108). Removed rows are not editable."""
    location = get_object_or_404(PickupLocation, pk=pk, deleted_at__isnull=True)

    if request.method == "POST":
        form = PickupLocationPortalForm(request.POST)
        if form.is_valid():
            location.name = form.cleaned_data["name"]
            location.description = form.cleaned_data["description"] or None
            location.save(update_fields=["name", "description"])
            messages.success(
                request,
                f"Pickup location \u201c{location.name}\u201d updated.",
            )
            return redirect(reverse("portal-pickup-locations"))
    else:
        form = PickupLocationPortalForm(
            initial={
                "name": location.name,
                "description": location.description or "",
            }
        )

    context = {
        "page_title": "Pickup Locations",
        "form": form,
        "editing": location,
        **_pickup_location_context(),
    }
    return render(request, "admin_portal/pickup_locations.html", context)


@require_POST
@staff_login_required
def pickup_location_soft_delete(request, pk: int):
    """
    Remove a location (CP-1108): the same `deleted_at` stamp the API's
    DELETE applies, so the listing-creation dropdown drops it immediately.
    """
    location = get_object_or_404(PickupLocation, pk=pk, deleted_at__isnull=True)
    location.deleted_at = timezone.now()
    location.save(update_fields=["deleted_at"])
    messages.success(
        request,
        f"Pickup location \u201c{location.name}\u201d removed.",
    )
    return redirect(reverse("portal-pickup-locations"))


@require_POST
@staff_login_required
def pickup_location_restore(request, pk: int):
    """
    Restore a removed location (CP-1108). Portal-only convenience (D-30):
    the API has no un-delete counterpart, so this is the supported way back.
    """
    location = get_object_or_404(PickupLocation, pk=pk, deleted_at__isnull=False)
    location.deleted_at = None
    location.save(update_fields=["deleted_at"])
    messages.success(
        request,
        f"Pickup location “{location.name}” restored.",
    )
    return redirect(reverse("portal-pickup-locations"))


# ---------------------------------------------------------------------------
# Listing categories (portal mirror of the `/admin/` category CRUD)
#
# Listing categories are the platform-wide pick list the Lender chooses from
# when publishing a listing (CP-401). They are created and renamed by an
# administrator; the mobile app only ever reads them through
# `GET /api/v1/listings/categories/`. Because the list is empty on a fresh
# database, publishing a listing is impossible until an administrator fills it
# in -- which is what this page is for.


class ListingCategoryPortalForm(forms.Form):
    """
    The `ListingCategory` rules restated for a server-rendered form: a trimmed,
    non-blank name of at most 100 characters that no other category uses, and
    an optional description.
    """

    name = forms.CharField(
        max_length=100,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "class": "field-input",
                "placeholder": "e.g. Textbooks",
            }
        ),
        error_messages={"required": "Category name cannot be blank."},
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "field-input",
                "rows": 3,
                "placeholder": "What belongs in this category (optional)",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)

    def clean_name(self) -> str:
        name = self.cleaned_data["name"]
        clash = ListingCategory.objects.filter(name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"A category named “{name}” already exists.")
        return name


def _listing_category_context() -> dict:
    """Shared context for the category pages."""
    return {
        "active_nav": "categories",
        "categories": ListingCategory.objects.annotate(
            listing_count=Count("listings")
        ).order_by("name"),
        "nav_verification_count": _identity_document_tab_counts()["pending"],
        "nav_reports_count": _open_reports_count(),
    }


@staff_login_required
def listing_categories(request):
    """
    Category configuration: the pick list Lenders publish from, with an add
    form. Creating a category follows PRG like the rest of the portal;
    validation errors re-render the form inline.
    """
    if request.method == "POST":
        form = ListingCategoryPortalForm(request.POST)
        if form.is_valid():
            ListingCategory.objects.create(
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"] or "",
            )
            messages.success(
                request,
                f"Category “{form.cleaned_data['name']}” added.",
            )
            return redirect(reverse("portal-listing-categories"))
    else:
        form = ListingCategoryPortalForm()

    context = {
        "page_title": "Categories",
        "form": form,
        **_listing_category_context(),
    }
    return render(request, "admin_portal/categories.html", context)


@staff_login_required
def listing_category_edit(request, pk: int):
    """Rename a category or change its description."""
    category = get_object_or_404(ListingCategory, pk=pk)

    if request.method == "POST":
        form = ListingCategoryPortalForm(request.POST, instance=category)
        if form.is_valid():
            category.name = form.cleaned_data["name"]
            category.description = form.cleaned_data["description"] or ""
            category.save(update_fields=["name", "description"])
            messages.success(
                request,
                f"Category “{category.name}” updated.",
            )
            return redirect(reverse("portal-listing-categories"))
    else:
        form = ListingCategoryPortalForm(
            initial={
                "name": category.name,
                "description": category.description or "",
            },
            instance=category,
        )

    context = {
        "page_title": "Categories",
        "form": form,
        "editing": category,
        **_listing_category_context(),
    }
    return render(request, "admin_portal/categories.html", context)


@require_POST
@staff_login_required
def listing_category_delete(request, pk: int):
    """
    Delete a category. `Listing.category` is `on_delete=PROTECT`, so a category
    that listings already point at cannot be deleted -- the admin is told which
    listings are in the way instead of getting a database error.
    """
    category = get_object_or_404(ListingCategory, pk=pk)
    in_use = category.listings.count()
    if in_use:
        messages.error(
            request,
            f"“{category.name}” is used by {in_use} listing"
            f"{'s' if in_use != 1 else ''} and cannot be deleted. "
            "Rename it instead, or move the listings to another category.",
        )
        return redirect(reverse("portal-listing-categories"))

    name = category.name
    category.delete()
    messages.success(request, f"Category “{name}” deleted.")
    return redirect(reverse("portal-listing-categories"))
