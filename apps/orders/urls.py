from django.urls import path

from .views import AcceptBorrowRequestView, BorrowRequestView, DeclineBorrowRequestView

urlpatterns = [
    path("orders/", BorrowRequestView.as_view(), name="order-request"),
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
]
