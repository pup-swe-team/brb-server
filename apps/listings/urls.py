from django.urls import path

from .views import (
    ListingDetailView,
    ListingSearchView,
    PickupLocationDetailView,
    PickupLocationListCreateView,
)

urlpatterns = [
    path(
        "listings/",
        ListingSearchView.as_view(),
        name="listing-search",
    ),
    path(
        "listings/<int:pk>/",
        ListingDetailView.as_view(),
        name="listing-detail",
    ),
    path(
        "pickup-locations/",
        PickupLocationListCreateView.as_view(),
        name="pickup-location-list-create",
    ),
    path(
        "pickup-locations/<int:pk>/",
        PickupLocationDetailView.as_view(),
        name="pickup-location-detail",
    ),
    path("<int:pk>", ListingDetailView.as_view(), name="listing-detail-legacy"),
]
