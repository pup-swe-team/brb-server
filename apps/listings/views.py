from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsIdentityVerified

from .models import Listing, PickupLocation
from .permissions import IsActiveLender, IsAdminOrReadOnly, IsOwnerOrReadOnly
from .selectors import search_listings
from .serializers import (
    ListingCreateSerializer,
    ListingSearchQuerySerializer,
    ListingSearchResultSerializer,
    ListingSerializer,
    ListingUpdateSerializer,
    PickupLocationSerializer,
)
from .services import deactivate_listing, delete_listing, reactivate_listing


class ListingCollectionView(generics.ListCreateAPIView):
    """
    The /api/v1/listings/ collection serves both browse/search (GET, CP-301)
    and publishing (POST, CP-401). POST additionally requires identity
    verification and active lender status.
    """

    queryset = Listing.objects.all()
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ListingCreateSerializer
        return ListingSearchResultSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsIdentityVerified(), IsActiveLender()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if self.request.method != "GET":
            return Listing.objects.all()
        query_serializer = ListingSearchQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        return search_listings(**query_serializer.validated_data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = serializer.save()
        response_data = ListingSerializer(listing, context={"request": request}).data
        headers = self.get_success_headers(response_data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or soft-delete a resource listing (CP-303, CP-402)."""

    permission_classes = (IsOwnerOrReadOnly,)
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
        "blocked_dates",
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
