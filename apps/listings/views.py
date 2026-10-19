from django.utils import timezone
from rest_framework import generics

from .models import Listing, PickupLocation
from .permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from .serializers import ListingSerializer, PickupLocationSerializer


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
