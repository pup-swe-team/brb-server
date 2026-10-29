from django.urls import path

from .views import CheckOverdueOrdersView, DeactivateUnverifiedAccountsView

urlpatterns = [
    path(
        "deactivate-unverified/",
        DeactivateUnverifiedAccountsView.as_view(),
        name="job-deactivate-unverified",
    ),
    path(
        "check-overdue/",
        CheckOverdueOrdersView.as_view(),
        name="job-check-overdue",
    ),
]
