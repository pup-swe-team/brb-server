"""
URL configuration for brb_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as serve_media

from apps.core.views import HealthView
from apps.listings.views import AdminRemoveListingView
from apps.reviews.views import AdminRemoveReviewView
from apps.users.dashboards import BorrowerDashboardView, LenderDashboardView
from apps.users.views import (
    AdminBanUserView,
    AdminReinstateUserView,
    AdminRevokeLenderView,
    AdminSuspendUserView,
    AdminUserListView,
    DeactivateAccountView,
)

urlpatterns = [
    # Render health check — keep at root so it answers before any DB/CDN work.
    path("healthz/", HealthView.as_view(), name="healthz"),
    path("admin/", admin.site.urls),
    path("portal/", include("apps.users.portal_urls")),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/jobs/", include("apps.core.urls")),
    path("api/v1/identity/", include("apps.users.identity_urls")),
    path("api/v1/lenders/", include("apps.users.lender_urls")),
    path(
        "api/v1/admin/listings/<int:pk>/",
        AdminRemoveListingView.as_view(),
        name="api-admin-remove-listing",
    ),
    path(
        "api/v1/admin/reviews/<int:pk>/",
        AdminRemoveReviewView.as_view(),
        name="api-admin-remove-review",
    ),
    path("api/v1/", include("apps.codes.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.listings.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    # Uploads (listing photos, profile images). Render has no nginx and
    # DEBUG=False, so nothing else serves MEDIA_ROOT — see DECISIONS.md D-26.
    path(
        "media/<path:path>",
        serve_media,
        {"document_root": settings.MEDIA_ROOT},
        name="media-serve",
    ),
    path(
        "api/v1/dashboard/borrower/",
        BorrowerDashboardView.as_view(),
        name="api-dashboard-borrower",
    ),
    path(
        "api/v1/dashboard/lender/",
        LenderDashboardView.as_view(),
        name="api-dashboard-lender",
    ),
    path(
        "api/v1/auth/borrower-dashboard/",
        BorrowerDashboardView.as_view(),
        name="api-auth-borrower-dashboard",
    ),
    path(
        "api/v1/auth/lender-dashboard/",
        LenderDashboardView.as_view(),
        name="api-auth-lender-dashboard",
    ),
    path(
        "api/v1/users/me/deactivate/",
        DeactivateAccountView.as_view(),
        name="api-users-me-deactivate",
    ),
    path(
        "api/v1/users/<int:pk>/revoke-lender/",
        AdminRevokeLenderView.as_view(),
        name="api-admin-revoke-lender",
    ),
    path(
        "api/v1/users/me/borrower-dashboard/",
        BorrowerDashboardView.as_view(),
        name="api-users-me-borrower-dashboard",
    ),
    path(
        "api/v1/users/me/lender-dashboard/",
        LenderDashboardView.as_view(),
        name="api-users-me-lender-dashboard",
    ),
    path(
        "api/v1/admin/users/",
        AdminUserListView.as_view(),
        name="api-admin-user-list",
    ),
    path(
        "api/v1/admin/users/<int:pk>/suspend/",
        AdminSuspendUserView.as_view(),
        name="api-admin-user-suspend",
    ),
    path(
        "api/v1/admin/users/<int:pk>/reinstate/",
        AdminReinstateUserView.as_view(),
        name="api-admin-user-reinstate",
    ),
    path(
        "api/v1/admin/users/<int:pk>/ban/",
        AdminBanUserView.as_view(),
        name="api-admin-user-ban",
    ),
    path(
        "api/v1/users/",
        AdminUserListView.as_view(),
        name="api-users-list",
    ),
    path(
        "api/v1/users/<int:pk>/suspend/",
        AdminSuspendUserView.as_view(),
        name="api-users-suspend",
    ),
    path(
        "api/v1/users/<int:pk>/reinstate/",
        AdminReinstateUserView.as_view(),
        name="api-users-reinstate",
    ),
    path(
        "api/v1/users/<int:pk>/ban/",
        AdminBanUserView.as_view(),
        name="api-users-ban",
    ),
]
