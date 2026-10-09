# Create your views here.

from rest_framework import generics
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import Listing, PickupLocation
from .permissions import IsOwnerOrReadOnly
from .serializers import ListingSerializer, PickupLocationSerializer


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsOwnerOrReadOnly,)
    serializer_class = ListingSerializer
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
    )


class PickupLocationListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
    paginate_by = 10


class PickupLocationCreateRetrieveDestroyView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
