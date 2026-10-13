from django.urls import path

from .views import (
    ListingCreateView,
    ListingDetailView,
    PickupLocationCreateRetrieveDestroyView,
    PickupLocationListView,
)

urlpatterns = [
    path("listings/", ListingCreateView.as_view(), name="listing-create"),
    path(
        "listings/<int:pk>/",
        ListingDetailView.as_view(),
        name="listing-detail-prefixed",
    ),
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
