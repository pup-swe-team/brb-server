"""Lender directory and profile routes (CP-302, CP-304).

Kept separate from auth and identity routes to maintain clear domain boundaries.
"""

from django.urls import path

from .views import LenderProfileView, LenderSearchView

urlpatterns = [
    path("", LenderSearchView.as_view(), name="lender-search"),
    path("<int:pk>/", LenderProfileView.as_view(), name="lender-profile"),
]
