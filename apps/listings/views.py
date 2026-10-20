from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsIdentityVerified

from .models import Listing, PickupLocation
from .permissions import IsActiveLender, IsOwnerOrReadOnly
from .serializers import (
    ListingCreateSerializer,
    ListingSerializer,
    ListingUpdateSerializer,
    PickupLocationSerializer,
)
from .services import deactivate_listing, delete_listing, reactivate_listing


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or soft-delete a resource listing (CP-303, CP-402)."""

    permission_classes = (IsOwnerOrReadOnly,)
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
    )

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ListingUpdateSerializer
        return ListingSerializer

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        listing = serializer.save()
        # Re-fetch so photos and availability windows replaced inside
        # update_listing() are not served from the stale prefetch cache.
        listing = self.get_queryset().get(pk=listing.pk)
        response_data = ListingSerializer(listing, context={"request": request}).data
        return Response(response_data, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        delete_listing(listing=instance)


class ListingDeactivateView(APIView):
    """Soft-remove a listing from search by transitioning its status to 'deactivated' (CP-402)."""

    permission_classes = (IsAuthenticated, IsOwnerOrReadOnly)

    def post(self, request, pk: int):
        listing = get_object_or_404(Listing, pk=pk)
        self.check_object_permissions(request, listing)
        updated_listing = deactivate_listing(listing=listing)
        data = ListingSerializer(updated_listing, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)


class ListingReactivateView(APIView):
    """Restore a deactivated listing back to 'active' status (CP-402)."""

    permission_classes = (IsAuthenticated, IsOwnerOrReadOnly)

    def post(self, request, pk: int):
        listing = get_object_or_404(Listing, pk=pk)
        self.check_object_permissions(request, listing)
        updated_listing = reactivate_listing(listing=listing)
        data = ListingSerializer(updated_listing, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)


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


class PickupLocationCreateRetrieveDestroyView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsAdminUser,)
    serializer_class = PickupLocationSerializer
    queryset = PickupLocation.objects.all().order_by("name")

    def perform_destroy(self, instance: PickupLocation) -> None:
        try:
            instance.delete()
        except ProtectedError as exc:
            raise ValidationError(
                {
                    "detail": "Cannot delete a pickup location that is still used by listings."
                }
            ) from exc
