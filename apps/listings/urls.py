from django.urls import path

from .views import (
    ListingCollectionView,
    ListingDeactivateView,
    ListingDetailView,
    ListingReactivateView,
    PickupLocationDetailView,
    PickupLocationListCreateView,
)

urlpatterns = [
    # GET = search listings (CP-301); POST = publish a listing (CP-401).
    path("listings/", ListingCollectionView.as_view(), name="listing-create"),
    path(
        "listings/<int:pk>/",
        ListingDetailView.as_view(),
        name="listing-detail",
    ),
    path(
        "listings/<int:pk>/deactivate/",
        ListingDeactivateView.as_view(),
        name="listing-deactivate",
    ),
    path(
        "listings/<int:pk>/reactivate/",
        ListingReactivateView.as_view(),
        name="listing-reactivate",
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
