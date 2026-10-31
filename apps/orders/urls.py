"""URL routes for order lifecycle (CP-501, CP-502, CP-503) and unreturned cases/status overrides (CP-506)."""

from django.urls import path

from .views import (
    AcceptBorrowRequestView,
    BorrowRequestView,
    CancelOrderView,
    CloseUnreturnedCaseView,
    DeclineBorrowRequestView,
    EscalateUnreturnedCaseView,
    OrderDetailView,
    OrderStatusOverrideView,
    UnreturnedCaseDetailView,
    UnreturnedCaseListView,
)

urlpatterns = [
    path("orders/", BorrowRequestView.as_view(), name="order-request"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<int:pk>/accept/",
        AcceptBorrowRequestView.as_view(),
        name="order-accept",
    ),
    path(
        "orders/<int:pk>/decline/",
        DeclineBorrowRequestView.as_view(),
        name="order-decline",
    ),
    path("orders/<int:pk>/cancel/", CancelOrderView.as_view(), name="order-cancel"),
    path(
        "orders/<int:pk>/override-status/",
        OrderStatusOverrideView.as_view(),
        name="order-override-status",
    ),
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
]
