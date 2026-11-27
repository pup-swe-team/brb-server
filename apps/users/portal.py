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

from django import forms
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import DateFormat
from django.views.decorators.http import require_POST

from apps.audit.services import log_admin_document_access
from apps.listings.models import Listing, ListingCategory, ListingStatus, PickupLocation
from apps.orders.models import Dispute, Order, UnreturnedCase
from apps.orders.selectors import (
    get_dispute_dossier,
    get_unreturned_case_dossier,
    list_disputes,
    list_unreturned_cases,
)
from apps.orders.services import (
    OrderCaseConflictError,
    close_unreturned_case,
    escalate_dispute,
    escalate_unreturned_case,
    resolve_dispute,
)
from apps.reports.models import (
    ListingReport,
    MessageReport,
    ReviewReport,
    UserReport,
)
from apps.reports.services import ReportStateConflictError, resolve_report
from apps.reviews.models import Review

from .admin_selectors import (
    get_admin_dashboard_metrics,
    get_portal_nav_counts,
)
from .constants import (
    IDENTITY_DOCUMENT_STATUS_PENDING,
    IDENTITY_DOCUMENT_TYPE_PUP_ID,
    PUP_ID_NUMBER_REGEX,
)
from .encryption import decrypt_document_data, detect_document_content_type
from .models import IdentityDocument, LenderRevocation, User
from .services import review_identity_document

# Display labels for the two accepted document types (CP-105 lookup rows).
IDENTITY_DOCUMENT_TYPE_LABELS = {
    "pup_id": "PUP ID",
    "government_id": "Government-issued ID",
}

# The order-status rows the dashboard chart highlights, covering all 11 lifecycle statuses.
DASHBOARD_ORDER_STATUSES = (
    "requested",
    "confirmed",
    "active",
    "overdue",
    "unreturned",
    "returned",
    "disputed",
    "completed",
    "declined",
    "expired",
    "cancelled",
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
    """Format timestamp using local timezone (Asia/Manila / UTC+8)."""
    if not timestamp:
        return ""
    local = timezone.localtime(timestamp)
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    if local.date() == timezone.localdate():
        return f"Today, {hour}:{local.minute:02d} {ampm}"
    return f"{DateFormat(local).format('M. j, Y')}, {hour}:{local.minute:02d} {ampm}"


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
    return get_portal_nav_counts()["nav_reports_count"]


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
            "iso_time": timezone.localtime(stamp).isoformat() if stamp else "",
            "full_time": (
                timezone.localtime(stamp).strftime("%b. %d, %Y, %I:%M %p")
                if stamp
                else ""
            ),
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
    Overview page (screen 77 / CP-1107): summary stat cards, orders-by-status chart,
    and recent activity feed backed by the shared `get_admin_dashboard_metrics()` selector.
    """
    metrics = get_admin_dashboard_metrics()
    orders_by_status = metrics["orders_by_status"]
    order_rows = [
        {"name": name, "total": orders_by_status.get(name, 0)}
        for name in DASHBOARD_ORDER_STATUSES
    ]
    max_orders = max((row["total"] for row in order_rows), default=0)
    for row in order_rows:
        row["percent"] = round(row["total"] / max_orders * 100) if max_orders else 0

    stats = {
        "total_users": metrics["total_users"],
        "new_users_this_month": metrics["new_users_this_month"],
        "active_listings": metrics["active_listings"],
        "listings_added_week": metrics["listings_added_this_week"],
        "open_reports": metrics["open_reports"],
        "flagged_users_pending": metrics["reports"]["flagged_users_pending_review"],
        "pending_verifications": metrics["pending_verifications"],
        "pending_days": metrics["oldest_pending_verification_days"],
        "open_disputes": metrics["open_disputes"],
        "open_unreturned_cases": metrics["open_unreturned_cases"],
        "total_orders": metrics["total_orders"],
    }

    context = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
        "stats": stats,
        "orders_by_status_rows": order_rows,
        "activity": _recent_activity(),
        "current_time": timezone.localtime(timezone.now()),
        "nav_verification_count": metrics["pending_verifications"],
        "nav_reports_count": metrics["open_reports"],
        "nav_unreturned_count": metrics["open_unreturned_cases"],
        "nav_disputes_count": metrics["open_disputes"],
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
    messages.success(request, f"Category “{name}” removed.")
    return redirect(reverse("portal-listing-categories"))


# --- Listings & Reviews Moderation (CP-1110 / CP-1102) ---


@staff_login_required
def listings_reviews(request):
    """
    Moderation workspace for listings and reviews (CP-1110, mirroring CP-1102).
    Allows staff to browse, search, and remove rule-violating listings and reviews.
    """
    tab = request.GET.get("tab", "listings").strip().lower()
    if tab not in ("listings", "reviews"):
        tab = "listings"

    query = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "all").strip().lower()

    active_status = ListingStatus.objects.filter(name="active").first()
    deleted_status = ListingStatus.objects.filter(name="deleted").first()

    total_listings = Listing.objects.count()
    active_listings_count = (
        Listing.objects.filter(status=active_status).count() if active_status else 0
    )
    total_reviews = Review.objects.count()
    active_reviews_count = Review.objects.filter(deleted_at__isnull=True).count()

    if tab == "listings":
        listings_qs = Listing.objects.select_related(
            "lender", "category", "status"
        ).order_by("-created_at", "-id")
        if filter_status == "active" and active_status:
            listings_qs = listings_qs.filter(status=active_status)
        elif filter_status == "deleted" and deleted_status:
            listings_qs = listings_qs.filter(status=deleted_status)
        elif filter_status == "deactivated":
            listings_qs = listings_qs.filter(status__name="deactivated")

        if query:
            listings_qs = listings_qs.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(lender__full_name__icontains=query)
                | Q(lender__email__icontains=query)
            )

        paginator = Paginator(listings_qs, 20)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)
    else:
        reviews_qs = Review.objects.select_related(
            "reviewer", "order", "order__borrower", "order__listing__lender"
        ).order_by("-created_at", "-id")
        if filter_status == "active":
            reviews_qs = reviews_qs.filter(deleted_at__isnull=True)
        elif filter_status == "deleted":
            reviews_qs = reviews_qs.filter(deleted_at__isnull=False)

        if query:
            reviews_qs = reviews_qs.filter(
                Q(comment__icontains=query)
                | Q(reviewer__full_name__icontains=query)
                | Q(reviewer__email__icontains=query)
            )

        paginator = Paginator(reviews_qs, 20)
        page_num = request.GET.get("page", 1)
        page = paginator.get_page(page_num)

    context = {
        "page_title": "Listings & Reviews Moderation",
        "active_nav": "listings_reviews",
        "tab": tab,
        "query": query,
        "filter_status": filter_status,
        "page": page,
        "paginator": paginator,
        "start_index": page.start_index() or 0,
        "end_index": page.end_index() or paginator.count,
        "total_listings": total_listings,
        "active_listings_count": active_listings_count,
        "total_reviews": total_reviews,
        "active_reviews_count": active_reviews_count,
        "nav_verification_count": _identity_document_tab_counts()["pending"],
        "nav_reports_count": _open_reports_count(),
    }
    return render(request, "admin_portal/listings_reviews.html", context)


@require_POST
@staff_login_required
def listing_remove(request, pk: int):
    """Admin removes a listing from the portal (CP-1110 / CP-1102)."""
    listing = get_object_or_404(Listing, pk=pk)
    from apps.listings.services import admin_remove_listing

    admin_remove_listing(listing_id=pk)
    messages.success(request, f"Listing “{listing.title}” has been removed.")
    return redirect(f"{reverse('portal-listings-reviews')}?tab=listings")


@require_POST
@staff_login_required
def review_remove(request, pk: int):
    """Admin removes a review from the portal (CP-1110 / CP-1102)."""
    review = get_object_or_404(Review, pk=pk)
    from apps.reviews.services import admin_remove_review

    admin_remove_review(review_id=review.pk)
    messages.success(request, f"Review #{review.pk} has been removed.")
    return redirect(f"{reverse('portal-listings-reviews')}?tab=reviews")


@staff_login_required
def users_roles(request):
    """
    Search and moderate users and their roles (CP-1109 / CP-1101).
    """
    from apps.users.selectors import search_admin_users

    query = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "all")
    filter_role = request.GET.get("role", "all")
    filter_lender = request.GET.get("lender", "all")

    users_qs = search_admin_users(
        q=query if query else None,
        account_status=filter_status if filter_status != "all" else None,
        affiliation=filter_role if filter_role != "all" else None,
        lender_status=filter_lender if filter_lender != "all" else None,
    )

    total_users = User.objects.count()
    active_users_count = User.objects.filter(
        account_status=User.AccountStatusChoices.ACTIVE
    ).count()
    suspended_users_count = User.objects.filter(
        account_status=User.AccountStatusChoices.SUSPENDED
    ).count()
    banned_users_count = User.objects.filter(
        account_status=User.AccountStatusChoices.BANNED
    ).count()
    active_lenders_count = User.objects.filter(
        lender_status=User.LenderStatusChoices.ACTIVE
    ).count()

    paginator = Paginator(users_qs, 20)
    page_num = request.GET.get("page", 1)
    page = paginator.get_page(page_num)

    context = {
        "page_title": "Users & Roles Moderation",
        "active_nav": "users_roles",
        "query": query,
        "filter_status": filter_status,
        "filter_role": filter_role,
        "filter_lender": filter_lender,
        "page": page,
        "paginator": paginator,
        "start_index": page.start_index() or 0,
        "end_index": page.end_index() or paginator.count,
        "total_users": total_users,
        "active_users_count": active_users_count,
        "suspended_users_count": suspended_users_count,
        "banned_users_count": banned_users_count,
        "active_lenders_count": active_lenders_count,
        "nav_verification_count": _identity_document_tab_counts()["pending"],
        "nav_reports_count": _open_reports_count(),
        "revocation_reasons": LenderRevocation.Reason.choices,
    }
    return render(request, "admin_portal/users_roles.html", context)


@require_POST
@staff_login_required
def user_suspend(request, pk: int):
    """Admin suspends a user from the portal (CP-1109 / CP-1101 / TC-103)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()

    if user.pk == request.user.pk:
        messages.error(request, "You cannot suspend your own account.")
    elif user.is_superuser:
        messages.error(request, "Superuser accounts cannot be suspended.")
    else:
        from apps.users.services import suspend_user

        suspend_user(user=user, actor=request.user, reason=reason)
        messages.success(
            request, f"User “{user.full_name or user.email}” has been suspended."
        )
    return redirect(reverse("portal-users"))


@require_POST
@staff_login_required
def user_reinstate(request, pk: int):
    """Admin reinstates a suspended user from the portal (CP-1109 / CP-1101 / TC-104)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()

    from rest_framework.exceptions import ValidationError

    from apps.users.services import reinstate_user

    try:
        reinstate_user(user=user, actor=request.user, reason=reason)
        messages.success(
            request, f"User “{user.full_name or user.email}” has been reinstated."
        )
    except ValidationError as exc:
        msg = (
            exc.detail.get("detail", str(exc))
            if isinstance(exc.detail, dict)
            else str(exc.detail)
        )
        messages.error(request, msg)
    return redirect(reverse("portal-users"))


@require_POST
@staff_login_required
def user_ban(request, pk: int):
    """Admin permanently bans a user from the portal (CP-1109 / CP-1101 / TC-105)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()

    if user.pk == request.user.pk:
        messages.error(request, "You cannot ban your own account.")
    elif user.is_superuser:
        messages.error(request, "Superuser accounts cannot be banned.")
    else:
        from apps.users.services import ban_user

        ban_user(user=user, actor=request.user, reason=reason)
        messages.success(
            request,
            f"User “{user.full_name or user.email}” has been permanently banned.",
        )
    return redirect(reverse("portal-users"))


@require_POST
@staff_login_required
def user_revoke_lender(request, pk: int):
    """Admin revokes lender role for a user from the portal (CP-1109 / CP-206)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip() or LenderRevocation.Reason.POLICY
    detail = request.POST.get("detail", "").strip()

    from apps.users.services import revoke_lender_role

    try:
        revoke_lender_role(
            user=user,
            actor=request.user,
            source=LenderRevocation.Source.ADMIN,
            reason=reason,
            detail=detail,
        )
        messages.success(
            request, f"Lender status revoked for “{user.full_name or user.email}”."
        )
    except (ValidationError, PermissionDenied, Exception) as exc:  # noqa: BLE001
        messages.error(request, f"Could not revoke lender role: {exc}")
    return redirect(reverse("portal-users"))


@require_POST
@staff_login_required
def user_confirm_flag(request, pk: int):
    """Admin confirms an auto-flagged user's moderation flag from the portal (CP-902)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()

    if user.pk == request.user.pk:
        messages.error(request, "You cannot flag your own account.")
    elif user.is_superuser:
        messages.error(request, "Superuser accounts cannot be flagged.")
    else:
        from apps.users.services import confirm_user_flag

        confirm_user_flag(user=user, actor=request.user, reason=reason)
        messages.success(
            request,
            f"Moderation flag confirmed for “{user.full_name or user.email}”. Listing and borrow creation restricted.",
        )
    next_url = request.POST.get("next") or reverse("portal-users")
    return redirect(next_url)


@require_POST
@staff_login_required
def user_dismiss_flag(request, pk: int):
    """Admin dismisses/clears a user's moderation flag from the portal (CP-902)."""
    user = get_object_or_404(User, pk=pk)
    reason = request.POST.get("reason", "").strip()

    from apps.users.services import dismiss_user_flag

    dismiss_user_flag(user=user, actor=request.user, reason=reason)
    messages.success(
        request,
        f"Moderation flag dismissed for “{user.full_name or user.email}”.",
    )
    next_url = request.POST.get("next") or reverse("portal-users")
    return redirect(next_url)


@require_POST
@staff_login_required
def user_clear_lender_hold(request, pk: int):
    """Admin clears lender reapplication hold for a revoked user from the portal (CP-206 / CP-1109)."""
    user = get_object_or_404(User, pk=pk)
    from apps.users.services import clear_lender_reapplication_hold

    try:
        if clear_lender_reapplication_hold(user=user, actor=request.user):
            messages.success(
                request,
                f"Lender application hold cleared for “{user.full_name or user.email}”. They can now reapply as a Lender.",
            )
        else:
            messages.error(
                request,
                f"Could not clear hold for “{user.full_name or user.email}” (user not on reapplication hold).",
            )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Could not clear lender hold: {exc}")
    return redirect(reverse("portal-users"))


@staff_login_required
def reports_queue(request):
    """
    Review queue for submitted reports (CP-1111 / CP-1103 / TC-109).
    Lists open and resolved reports for Users, Listings, Reviews, and Messages.
    """
    tab = request.GET.get("type", "all").strip().lower()
    status_filter = request.GET.get("status", "open").strip().lower()

    items = []

    # 1. User Reports
    if tab in ("all", "user"):
        qs = UserReport.objects.select_related(
            "reporter", "target_user", "category"
        ).order_by("-created_at")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        for r in qs[:100]:
            items.append(
                {
                    "id": r.pk,
                    "type": "user",
                    "type_label": "User Report",
                    "reporter": r.reporter,
                    "target_display": r.target_user.full_name or r.target_user.email,
                    "target_meta": f"Target User ID #{r.target_user.pk}",
                    "category": r.category.name if r.category else "Uncategorized",
                    "description": r.description,
                    "status": r.status,
                    "created_at": r.created_at,
                }
            )

    # 2. Listing Reports
    if tab in ("all", "listing"):
        qs = ListingReport.objects.select_related(
            "reporter", "target_listing", "target_listing__lender", "category"
        ).order_by("-created_at")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        for r in qs[:100]:
            items.append(
                {
                    "id": r.pk,
                    "type": "listing",
                    "type_label": "Listing Report",
                    "reporter": r.reporter,
                    "target_display": r.target_listing.title,
                    "target_meta": f"Listing #{r.target_listing.pk} · Lender: {r.target_listing.lender.full_name or r.target_listing.lender.email}",
                    "category": r.category.name if r.category else "Uncategorized",
                    "description": r.description,
                    "status": r.status,
                    "created_at": r.created_at,
                }
            )

    # 3. Review Reports
    if tab in ("all", "review"):
        qs = ReviewReport.objects.select_related(
            "reporter", "target_review", "target_review__reviewer", "category"
        ).order_by("-created_at")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        for r in qs[:100]:
            items.append(
                {
                    "id": r.pk,
                    "type": "review",
                    "type_label": "Review Report",
                    "reporter": r.reporter,
                    "target_display": f"Review #{r.target_review.pk} ({r.target_review.rating}★)",
                    "target_meta": f"Reviewer: {r.target_review.reviewer.full_name or r.target_review.reviewer.email}",
                    "category": r.category.name if r.category else "Uncategorized",
                    "description": r.description,
                    "status": r.status,
                    "created_at": r.created_at,
                }
            )

    # 4. Message Reports
    if tab in ("all", "message"):
        qs = MessageReport.objects.select_related(
            "reporter", "target_message", "target_message__sender", "category"
        ).order_by("-created_at")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        for r in qs[:100]:
            snippet = (
                r.target_message.content[:40] + "..."
                if len(r.target_message.content) > 40
                else r.target_message.content
            )
            items.append(
                {
                    "id": r.pk,
                    "type": "message",
                    "type_label": "Message Report",
                    "reporter": r.reporter,
                    "target_display": f"“{snippet}”",
                    "target_meta": f"Sender: {r.target_message.sender.full_name or r.target_message.sender.email}",
                    "category": r.category.name if r.category else "Uncategorized",
                    "description": r.description,
                    "status": r.status,
                    "created_at": r.created_at,
                }
            )

    # 5. Flagged User Accounts (CP-902 / TC-103)
    flagged_users_qs = User.objects.filter(
        Q(is_flagged=True) | Q(account_status=User.AccountStatusChoices.PENDING_REVIEW)
    ).order_by("-flagged_at", "-updated_at")
    flagged_users_count = flagged_users_qs.count()

    if tab in ("all", "flagged"):
        for u in flagged_users_qs[:50]:
            if status_filter == "open" and u.is_flag_confirmed:
                continue
            if status_filter == "resolved" and not u.is_flag_confirmed:
                continue
            items.append(
                {
                    "id": u.pk,
                    "type": "flagged_user",
                    "type_label": "Flagged User",
                    "reporter": u.flag_confirmed_by,
                    "reporter_name": (
                        "Automated (30-day threshold)"
                        if (u.is_flagged and not u.flag_confirmed_by)
                        else (
                            u.flag_confirmed_by.full_name
                            if u.flag_confirmed_by
                            else "System"
                        )
                    ),
                    "target_display": u.full_name or u.email,
                    "target_meta": f"User ID #{u.pk} · {u.get_account_status_display()}",
                    "category": (
                        "Auto-Flagged (CP-902)" if u.is_flagged else "Pending Review"
                    ),
                    "description": (
                        f"Account flagged for administrative review on {u.flagged_at.strftime('%b. %d, %Y') if u.flagged_at else 'recently'}. Action required."
                    ),
                    "status": "open" if not u.is_flag_confirmed else "resolved",
                    "created_at": u.flagged_at or u.updated_at,
                    "is_flagged_user": True,
                    "user_pk": u.pk,
                    "is_flag_confirmed": u.is_flag_confirmed,
                }
            )

    items.sort(key=lambda x: x["created_at"], reverse=True)

    user_open_count = UserReport.objects.filter(status="open").count()
    listing_open_count = ListingReport.objects.filter(status="open").count()
    review_open_count = ReviewReport.objects.filter(status="open").count()
    message_open_count = MessageReport.objects.filter(status="open").count()
    total_open_count = (
        user_open_count
        + listing_open_count
        + review_open_count
        + message_open_count
        + flagged_users_count
    )

    context = {
        "page_title": "Reports & Flags",
        "active_nav": "reports",
        "tab": tab,
        "status_filter": status_filter,
        "items": items,
        "flagged_users_count": flagged_users_count,
        "user_open_count": user_open_count,
        "listing_open_count": listing_open_count,
        "review_open_count": review_open_count,
        "message_open_count": message_open_count,
        "total_open_count": total_open_count,
        "nav_verification_count": _identity_document_tab_counts()["pending"],
        "nav_reports_count": total_open_count,
    }
    return render(request, "admin_portal/reports.html", context)


@require_POST
@staff_login_required
def report_resolve(request, report_type: str, pk: int):
    """Admin marks a report as resolved via the shared service layer (CP-1111 / CP-1103 / TC-109)."""
    from rest_framework.exceptions import ValidationError as DRFValidationError

    notes = request.POST.get("resolution_notes", "").strip()
    try:
        resolve_report(
            report_type=report_type,
            report_id=pk,
            admin=request.user,
            resolution_notes=notes,
        )
        messages.success(
            request, f"{report_type.title()} Report #{pk} has been marked as Resolved."
        )
    except ReportStateConflictError as exc:
        messages.error(request, str(exc.detail))
    except DRFValidationError:
        messages.error(request, "Invalid report type.")
        return redirect(reverse("portal-reports-queue"))

    return redirect(
        reverse("portal-reports-queue") + f"?type={report_type}&status=open"
    )


# ---------------------------------------------------------------------------
# CP-903 -- Damage / missing-item disputes moderation
# ---------------------------------------------------------------------------


@staff_login_required
def disputes_queue(request):
    """List damage/missing-item disputes with status filter tabs (CP-903)."""
    status_filter = request.GET.get("status", "open").strip().lower()
    if status_filter not in ("open", "escalated", "resolved", "all"):
        status_filter = "open"

    qs = list_disputes(status_filter=None if status_filter == "all" else status_filter)
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page", 1))

    counts = {
        "open": Dispute.objects.filter(status=Dispute.StatusChoices.OPEN).count(),
        "escalated": Dispute.objects.filter(
            status=Dispute.StatusChoices.ESCALATED
        ).count(),
        "resolved": Dispute.objects.filter(
            status=Dispute.StatusChoices.RESOLVED
        ).count(),
    }
    counts["all"] = sum(counts.values())

    context = {
        "page_title": "Disputes",
        "active_nav": "disputes",
        "status_filter": status_filter,
        "counts": counts,
        "page": page,
        "paginator": paginator,
        "start_index": page.start_index() or 0,
        "end_index": page.end_index() or paginator.count,
        **get_portal_nav_counts(),
    }
    return render(request, "admin_portal/disputes.html", context)


@staff_login_required
def dispute_detail(request, pk: int):
    """Full investigation dossier for a damage/missing-item dispute (CP-903)."""
    dossier = get_dispute_dossier(dispute_id=pk, admin=request.user, request=request)
    context = {
        "page_title": f"Dispute #{pk}",
        "active_nav": "disputes",
        "dossier": dossier,
        **get_portal_nav_counts(),
    }
    return render(request, "admin_portal/dispute_detail.html", context)


@require_POST
@staff_login_required
def dispute_resolve(request, pk: int):
    """Resolve a dispute to Completed via the shared service layer (CP-903)."""
    notes = request.POST.get("resolution_notes", "").strip()
    try:
        resolve_dispute(dispute_id=pk, admin=request.user, resolution_notes=notes)
        messages.success(
            request,
            f"Dispute #{pk} resolved and order marked as Completed.",
        )
    except OrderCaseConflictError as exc:
        messages.error(request, str(exc.detail))
    return redirect(reverse("portal-dispute-detail", args=[pk]))


@require_POST
@staff_login_required
def dispute_escalate(request, pk: int):
    """Escalate a dispute to PUP OSS via the shared service layer (CP-903)."""
    notes = request.POST.get("resolution_notes", "").strip()
    evidence_files = request.FILES.getlist("evidence")
    try:
        escalate_dispute(
            dispute_id=pk,
            admin=request.user,
            resolution_notes=notes,
            evidence_files=evidence_files,
        )
        messages.success(
            request,
            f"Dispute #{pk} escalated to PUP OSS for administrative review.",
        )
    except OrderCaseConflictError as exc:
        messages.error(request, str(exc.detail))
    return redirect(reverse("portal-dispute-detail", args=[pk]))


# ---------------------------------------------------------------------------
# CP-1103 / CP-506 / CP-1111 -- Unreturned cases moderation
# ---------------------------------------------------------------------------


@staff_login_required
def unreturned_cases_queue(request):
    """List UnreturnedCase records with status filter tabs (CP-1103, CP-506)."""
    status_filter = request.GET.get("status", "open").strip().lower()
    if status_filter not in ("open", "escalated", "returned", "unresolved", "all"):
        status_filter = "open"

    qs = list_unreturned_cases(
        status_filter=None if status_filter == "all" else status_filter
    )
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page", 1))

    counts = {
        "open": UnreturnedCase.objects.filter(status__name="open").count(),
        "escalated": UnreturnedCase.objects.filter(status__name="escalated").count(),
        "returned": UnreturnedCase.objects.filter(status__name="returned").count(),
        "unresolved": UnreturnedCase.objects.filter(status__name="unresolved").count(),
    }
    counts["all"] = sum(counts.values())

    context = {
        "page_title": "Unreturned Cases",
        "active_nav": "unreturned_cases",
        "status_filter": status_filter,
        "counts": counts,
        "page": page,
        "paginator": paginator,
        "start_index": page.start_index() or 0,
        "end_index": page.end_index() or paginator.count,
        **get_portal_nav_counts(),
    }
    return render(request, "admin_portal/unreturned_cases.html", context)


@staff_login_required
def unreturned_case_detail(request, pk: int):
    """Full investigation dossier for an UnreturnedCase (CP-1103, CP-506)."""
    dossier = get_unreturned_case_dossier(
        case_id=pk, admin=request.user, request=request
    )
    context = {
        "page_title": f"Unreturned Case #{pk}",
        "active_nav": "unreturned_cases",
        "dossier": dossier,
        **get_portal_nav_counts(),
    }
    return render(request, "admin_portal/unreturned_case_detail.html", context)


@require_POST
@staff_login_required
def unreturned_case_escalate(request, pk: int):
    """Escalate an UnreturnedCase to PUP OSS / Campus Security via shared service (CP-1103)."""
    notes = request.POST.get("resolution_notes", "").strip()
    evidence_files = request.FILES.getlist("evidence")
    escalate_unreturned_case(
        case_id=pk,
        admin=request.user,
        resolution_notes=notes,
        evidence_files=evidence_files,
    )
    messages.success(
        request,
        f"Unreturned Case #{pk} escalated to PUP OSS / Campus Security.",
    )
    return redirect(reverse("portal-unreturned-case-detail", args=[pk]))


@require_POST
@staff_login_required
def unreturned_case_close(request, pk: int):
    """Close an UnreturnedCase as 'returned' or 'unresolved' via shared service (CP-1103)."""
    from rest_framework.exceptions import ValidationError as DRFValidationError

    close_status = request.POST.get("status", "").strip().lower()
    notes = request.POST.get("resolution_notes", "").strip()
    try:
        close_unreturned_case(
            case_id=pk,
            admin=request.user,
            close_status=close_status,
            resolution_notes=notes,
        )
        messages.success(
            request,
            f"Unreturned Case #{pk} closed as {close_status.title()}.",
        )
    except (OrderCaseConflictError, DRFValidationError) as exc:
        messages.error(request, str(exc.detail))
    return redirect(reverse("portal-unreturned-case-detail", args=[pk]))
