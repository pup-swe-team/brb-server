from django.urls import path

from .views import (
    ListingDetailView,
    PickupLocationCreateRetrieveDestroyView,
    PickupLocationListView,
)

urlpatterns = [
    path("<int:pk>", ListingDetailView.as_view(), name="listing-detail"),
    path(
        "pickup-location/",
        PickupLocationListView.as_view(),
        name="pickup-location-list",
    ),
    path(
        "pickup-location/<int:pk>",
        PickupLocationCreateRetrieveDestroyView.as_view(),
        name="pickup-location-detail",
    ),
]
