"""URL routing for reporting users, listings, reviews, and messages (CP-901)."""

from django.urls import path

from .views import (
    ListingReportCreateView,
    MessageReportCreateView,
    ReportCategoriesListView,
    ReviewReportCreateView,
    UnifiedReportCreateView,
    UserReportCreateView,
)

urlpatterns = [
    path(
        "reports/categories/",
        ReportCategoriesListView.as_view(),
        name="report-categories",
    ),
    path(
        "reports/",
        UnifiedReportCreateView.as_view(),
        name="report-create",
    ),
    path(
        "reports/users/",
        UserReportCreateView.as_view(),
        name="report-user-create",
    ),
    path(
        "reports/listings/",
        ListingReportCreateView.as_view(),
        name="report-listing-create",
    ),
    path(
        "reports/reviews/",
        ReviewReportCreateView.as_view(),
        name="report-review-create",
    ),
    path(
        "reports/messages/",
        MessageReportCreateView.as_view(),
        name="report-message-create",
    ),
    path(
        "users/<int:pk>/report/",
        UserReportCreateView.as_view(),
        name="user-report-action",
    ),
    path(
        "listings/<int:pk>/report/",
        ListingReportCreateView.as_view(),
        name="listing-report-action",
    ),
    path(
        "reviews/<int:pk>/report/",
        ReviewReportCreateView.as_view(),
        name="review-report-action",
    ),
    path(
        "messages/<int:pk>/report/",
        MessageReportCreateView.as_view(),
        name="message-report-action",
    ),
]
