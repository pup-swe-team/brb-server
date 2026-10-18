from django.urls import path

from .views import (
    ListingDetailView,
    PickupLocationDetailView,
    PickupLocationListCreateView,
)

urlpatterns = [
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
    path("<int:pk>", ListingDetailView.as_view(), name="listing-detail"),
]
