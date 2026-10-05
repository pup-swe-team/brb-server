"""Identity verification routes (CP-105).

Kept apart from `urls.py`, which owns the `/api/v1/auth/` prefix. Identity
document submission is authenticated rather than public, and separating the two
keeps the public auth surface obvious at a glance.
"""

from django.urls import path

from .views import IdentityDocumentListView, IdentityDocumentSubmissionView

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
]
