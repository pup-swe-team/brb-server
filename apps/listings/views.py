# Create your views here.

from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from apps.users.permissions import IsIdentityVerified

from .models import Listing, PickupLocation
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
    """Publish an educational resource listing (FR6, FR7, CP-401)."""

    queryset = Listing.objects.all()
    serializer_class = ListingCreateSerializer
    permission_classes = (IsAuthenticated, IsIdentityVerified, IsActiveLender)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = serializer.save()
        response_data = ListingSerializer(listing, context={"request": request}).data
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)


class PickupLocationListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
    paginate_by = 10


class PickupLocationCreateRetrieveDestroyView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")
