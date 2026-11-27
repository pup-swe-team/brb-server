"""CoPUPAdmin portal routes (BE-BUG-0006, CP-1108).

Mounted at `/portal/`. These are Django-rendered pages for the administrator
verification workflow (screens 76, 77, 82, 83, 84) plus the pickup-location
management page (CP-1108, mirror of CP-1105). Everything under these routes
except the sign-in page requires a logged-in staff account
(`is_staff`, D-03) -- enforced in `apps.users.portal.staff_login_required`.
"""

from django.urls import path

from . import portal

urlpatterns = [
    path("login/", portal.AdminPortalLoginView(), name="portal-login"),
    path("logout/", portal.portal_logout, name="portal-logout"),
    path("", portal.dashboard, name="portal-dashboard"),
    path("verification/", portal.verification_queue, name="portal-verification-queue"),
    path(
        "verification/<int:pk>/",
        portal.verification_review,
        name="portal-verification-review",
    ),
    path(
        "verification/<int:pk>/review/",
        portal.verification_review_submit,
        name="portal-verification-review-submit",
    ),
    path(
        "pickup-locations/",
        portal.pickup_locations,
        name="portal-pickup-locations",
    ),
    path(
        "pickup-locations/<int:pk>/edit/",
        portal.pickup_location_edit,
        name="portal-pickup-location-edit",
    ),
    path(
        "pickup-locations/<int:pk>/delete/",
        portal.pickup_location_soft_delete,
        name="portal-pickup-location-delete",
    ),
    path(
        "pickup-locations/<int:pk>/restore/",
        portal.pickup_location_restore,
        name="portal-pickup-location-restore",
    ),
    # Listing categories -- the pick list Lenders publish from (CP-401).
    path(
        "categories/",
        portal.listing_categories,
        name="portal-listing-categories",
    ),
    path(
        "categories/<int:pk>/edit/",
        portal.listing_category_edit,
        name="portal-listing-category-edit",
    ),
    path(
        "categories/<int:pk>/delete/",
        portal.listing_category_delete,
        name="portal-listing-category-delete",
    ),
    # Listings & reviews moderation (CP-1110, mirror of CP-1102).
    path(
        "listings-reviews/",
        portal.listings_reviews,
        name="portal-listings-reviews",
    ),
    path(
        "listings/<int:pk>/remove/",
        portal.listing_remove,
        name="portal-listing-remove",
    ),
    path(
        "reviews/<int:pk>/remove/",
        portal.review_remove,
        name="portal-review-remove",
    ),
    # Users & roles moderation (CP-1109, mirror of CP-1101).
    path(
        "users/",
        portal.users_roles,
        name="portal-users",
    ),
    path(
        "users/<int:pk>/suspend/",
        portal.user_suspend,
        name="portal-user-suspend",
    ),
    path(
        "users/<int:pk>/reinstate/",
        portal.user_reinstate,
        name="portal-user-reinstate",
    ),
    path(
        "users/<int:pk>/ban/",
        portal.user_ban,
        name="portal-user-ban",
    ),
    path(
        "users/<int:pk>/revoke-lender/",
        portal.user_revoke_lender,
        name="portal-user-revoke-lender",
    ),
    path(
        "users/<int:pk>/clear-lender-hold/",
        portal.user_clear_lender_hold,
        name="portal-user-clear-lender-hold",
    ),
    path(
        "users/<int:pk>/confirm-flag/",
        portal.user_confirm_flag,
        name="portal-user-confirm-flag",
    ),
    path(
        "users/<int:pk>/dismiss-flag/",
        portal.user_dismiss_flag,
        name="portal-user-dismiss-flag",
    ),
    # Reports & flags moderation (CP-1111 / CP-1103 / TC-109).
    path(
        "reports/",
        portal.reports_queue,
        name="portal-reports-queue",
    ),
    path(
        "reports/<str:report_type>/<int:pk>/resolve/",
        portal.report_resolve,
        name="portal-report-resolve",
    ),
    # Retained chat conversation evidence viewer (CP-703).
    path(
        "conversations/<int:pk>/",
        portal.conversation_detail,
        name="portal-conversation-detail",
    ),
    # System parameters configuration (CP-1112 / CP-1104 / TC-111 / TC-112).
    path(
        "system-parameters/",
        portal.system_parameters,
        name="portal-system-parameters",
    ),
    # Audit log viewer (CP-1113 / CP-1106 / TC-115 / TC-116).
    path(
        "audit-log/",
        portal.audit_log_viewer,
        name="portal-audit-log",
    ),
    # Consolidated review queues (CP-1103 / TC-108 / TC-109 / TC-110).
    path(
        "queues/",
        portal.consolidated_review_queues,
        name="portal-review-queues",
    ),
    path(
        "unreturned/<int:pk>/resolve/",
        portal.unreturned_case_resolve,
        name="portal-unreturned-resolve",
    ),
    path(
        "unreturned/<int:pk>/escalate/",
        portal.unreturned_case_escalate,
        name="portal-unreturned-escalate",
    ),
]
