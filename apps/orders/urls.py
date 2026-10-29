"""URL routes for unreturned cases and manual order status corrections (CP-506)."""

from django.urls import path

from .views import (
    CloseUnreturnedCaseView,
    EscalateUnreturnedCaseView,
    OrderStatusOverrideView,
    UnreturnedCaseDetailView,
    UnreturnedCaseListView,
)

urlpatterns = [
    path(
        "unreturned-cases/",
        UnreturnedCaseListView.as_view(),
        name="unreturned-case-list",
    ),
    path(
        "unreturned-cases/<int:pk>/",
        UnreturnedCaseDetailView.as_view(),
        name="unreturned-case-detail",
    ),
    path(
        "unreturned-cases/<int:pk>/escalate/",
        EscalateUnreturnedCaseView.as_view(),
        name="unreturned-case-escalate",
    ),
    path(
        "unreturned-cases/<int:pk>/close/",
        CloseUnreturnedCaseView.as_view(),
        name="unreturned-case-close",
    ),
    path(
        "orders/<int:pk>/override-status/",
        OrderStatusOverrideView.as_view(),
        name="order-override-status",
    ),
]
