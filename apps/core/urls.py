from django.urls import path

from .views import DeactivateUnverifiedAccountsView, ExpireBorrowRequestsView

urlpatterns = [
    path(
        "deactivate-unverified/",
        DeactivateUnverifiedAccountsView.as_view(),
        name="job-deactivate-unverified",
    ),
    path(
        "expire-borrow-requests/",
        ExpireBorrowRequestsView.as_view(),
        name="job-expire-borrow-requests",
    ),
]
