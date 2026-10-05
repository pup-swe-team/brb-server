from django.urls import path

from .views import DeactivateUnverifiedAccountsView

urlpatterns = [
    path(
        "deactivate-unverified/",
        DeactivateUnverifiedAccountsView.as_view(),
        name="job-deactivate-unverified",
    ),
]
