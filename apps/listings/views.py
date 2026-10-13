# Create your views here.

from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import Listing, ListingStatus, PickupLocation
from .permissions import IsActiveLender, IsOwnerOrReadOnly
from .serializers import (
    ListingCreateSerializer,
    ListingSerializer,
    PickupLocationSerializer,
)


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsOwnerOrReadOnly,)
    serializer_class = ListingSerializer
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
    )


class ListingCreateView(generics.CreateAPIView):
    queryset = Listing.objects.all()
    serializer_class = ListingCreateSerializer
    permission_classes = (IsActiveLender,)  # Only those that are approved

    def perform_create(self, serializer):
        pending_status = get_object_or_404(
            ListingStatus,
            name="Pending",
        )

        serializer.save(
            lender=self.request.user,
            status=pending_status,
        )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)

        if response.status_code == 201:
            listing = self.get_queryset().get(pk=response.data["id"])
            response.data = ListingSerializer(listing).data

        return response


class PickupLocationListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
    paginate_by = 10


class PickupLocationCreateRetrieveDestroyView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
