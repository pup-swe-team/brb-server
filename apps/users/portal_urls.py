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
]
