"""Lender directory and profile routes (CP-302, CP-304).

Kept separate from auth and identity routes to maintain clear domain boundaries.
"""

from django.urls import path

from .views import LenderSearchView

urlpatterns = [
    path("", LenderSearchView.as_view(), name="lender-search"),
]
