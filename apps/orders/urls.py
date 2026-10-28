from django.urls import path

from .views import BorrowRequestView

urlpatterns = [
    path("orders/", BorrowRequestView.as_view(), name="order-request"),
]
