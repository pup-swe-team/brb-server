from django.utils import timezone
from rest_framework import generics, permissions

from .models import Listing, PickupLocation
from .permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from .selectors import search_listings
from .serializers import (
    ListingSearchQuerySerializer,
    ListingSearchResultSerializer,
    ListingSerializer,
    PickupLocationSerializer,
)


class ListingSearchView(generics.ListAPIView):
    """
    Search and filter active listings (CP-301).
    Supports keyword search (?q=), category, condition, pickup location,
    price range, free_only, date availability, and sorting.
    Excludes deactivated/deleted listings and suspended/revoked lenders.
    """

    serializer_class = ListingSearchResultSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        query_serializer = ListingSearchQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        return search_listings(**query_serializer.validated_data)


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ListingSerializer
    permission_classes = (IsOwnerOrReadOnly,)
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
        "blocked_dates",
    )


class PickupLocationListCreateView(generics.ListCreateAPIView):
    """
    List active pickup locations (authenticated users) or
    create a new designated pickup location (admin only, CP-1105).
    """

    serializer_class = PickupLocationSerializer
    permission_classes = (IsAdminOrReadOnly,)
    pagination_class = None

    def get_queryset(self):
        return PickupLocation.objects.filter(deleted_at__isnull=True).order_by("name")


class PickupLocationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve an active pickup location (authenticated users),
    update or soft-delete a pickup location (admin only, CP-1105).
    """

    serializer_class = PickupLocationSerializer
    permission_classes = (IsAdminOrReadOnly,)

    def get_queryset(self):
        return PickupLocation.objects.filter(deleted_at__isnull=True)

    def perform_destroy(self, instance: PickupLocation) -> None:
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])
