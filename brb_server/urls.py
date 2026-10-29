"""
URL configuration for brb_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
from apps.users.dashboards import BorrowerDashboardView, LenderDashboardView
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from apps.users.dashboards import BorrowerDashboardView, LenderDashboardView
from django.views.static import serve as serve_media

from apps.core.views import HealthView

urlpatterns = [
    # Render health check — keep at root so it answers before any DB/CDN work.
    path("healthz/", HealthView.as_view(), name="healthz"),
    path("admin/", admin.site.urls),
    path("portal/", include("apps.users.portal_urls")),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/jobs/", include("apps.core.urls")),
    path("api/v1/identity/", include("apps.users.identity_urls")),
    path("api/v1/lenders/", include("apps.users.lender_urls")),
    path("api/v1/", include("apps.codes.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.listings.urls")),
    path("api/v1/", include("apps.orders.urls")),
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
]
