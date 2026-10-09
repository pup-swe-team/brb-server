# Create your views here.

from rest_framework import generics

from .models import Listing
from .permissions import IsOwnerOrReadOnly
from .serializers import ListingSerializer


class ListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ListingSerializer
    permission_classes = (IsOwnerOrReadOnly,)
    queryset = Listing.objects.select_related(
        "lender", "category", "pickup_location", "status"
    ).prefetch_related(
        "photos",
        "availability_windows",
    )
