"""Identity verification routes (CP-105).

Kept apart from `urls.py`, which owns the `/api/v1/auth/` prefix. Identity
document submission is authenticated rather than public, and separating the two
keeps the public auth surface obvious at a glance.
"""

from django.urls import path

from .views import (
    IdentityDocumentDownloadView,
    IdentityDocumentListView,
    IdentityDocumentOwnerInfoView,
    IdentityDocumentReviewView,
    IdentityDocumentSubmissionView,
)

urlpatterns = [
    path(
        "documents/",
        IdentityDocumentSubmissionView.as_view(),
        name="identity-document-submit",
    ),
    path(
        "documents/list/",
        IdentityDocumentListView.as_view(),
        name="identity-document-list",
    ),
    path(
        "documents/<int:pk>/review/",
        IdentityDocumentReviewView.as_view(),
        name="identity-document-review",
    ),
    path(
        "documents/<int:pk>/download/",
        IdentityDocumentDownloadView.as_view(),
        name="identity-document-download",
    ),
    path(
        "documents/<int:pk>/owner-info/",
        IdentityDocumentOwnerInfoView.as_view(),
        name="identity-document-owner-info",
    ),
]
