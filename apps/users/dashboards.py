from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.listings.models import Listing
from apps.users.serializers import UserResponseSerializer
from apps.core.constants import BORROWING_LIMIT, DEFAULT_BORROWING_LIMIT
from apps.core.selectors import get_int_config


class BorrowerDashboardView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        user = request.user
        orders = (
            Order.objects.filter(borrower=user)
            .select_related("listing", "listing__lender", "status")
            .order_by("-created_at")
        )
        grouped = {
            "requested": [],
            "confirmed": [],
            "active": [],
            "overdue": [],
            "returned": [],
            "completed": [],
            "declined": [],
            "expired": [],
            "cancelled": [],
            "unreturned": [],
            "disputed": [],
            "past": [],
        }
        for order in orders:
            status_name = getattr(getattr(order, "status"), "name", "")
            data = {
                "id": order.id,
                "listing_id": order.listing_id,
                "listing_title": getattr(order.listing, "title", ""),
                "status": status_name,
                "start_date": order.start_date,
                "end_date": order.end_date,
                "created_at": order.created_at,
            }
            if status_name in grouped:
                grouped[status_name].append(data)
            else:
                grouped.setdefault(status_name, []).append(data)
        past_statuses = ["returned", "completed", "declined", "expired", "cancelled"]
        grouped["past"] = []
        for name in past_statuses:
            grouped["past"].extend(grouped.get(name, []))
        borrowing_limit = get_int_config(BORROWING_LIMIT, DEFAULT_BORROWING_LIMIT)
        items_held = orders.filter(
            status__name__in=["requested", "confirmed", "active", "overdue"]
        ).count()
        return Response(
            {
                "user": UserResponseSerializer(user, context={"request": request}).data,
                "verification_status": {
                    "email_verified": bool(user.email_verified_at),
                    "identity_verified": user.has_verified_identity(),
                },
                "borrowing_limit": borrowing_limit,
                "items_held": items_held,
                "orders": grouped,
            },
            status=status.HTTP_200_OK,
        )


class LenderDashboardView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        user = request.user
        listings = (
            Listing.objects.filter(lender=user)
            .select_related("category", "pickup_location", "status")
            .prefetch_related("photos")
            .order_by("-created_at")
        )
        listings_data = []
        for listing in listings:
            listings_data.append(
                {
                    "id": listing.id,
                    "title": listing.title,
                    "status": getattr(listing.status, "name", ""),
                    "category": getattr(listing.category, "name", ""),
                    "rate_per_day": float(listing.rate_per_day)
                    if listing.rate_per_day is not None
                    else None,
                    "created_at": listing.created_at,
                }
            )
        orders_on_listings = (
            Order.objects.filter(listing__lender=user)
            .select_related("listing", "borrower", "status")
            .order_by("-created_at")
        )
        incoming_requests = []
        ongoing = []
        past = []
        for order in orders_on_listings:
            status_name = getattr(getattr(order, "status"), "name", "")
            data = {
                "id": order.id,
                "listing_id": order.listing_id,
                "listing_title": getattr(order.listing, "title", ""),
                "borrower": {
                    "id": order.borrower_id,
                    "full_name": getattr(order.borrower, "full_name", ""),
                },
                "status": status_name,
                "start_date": order.start_date,
                "end_date": order.end_date,
                "created_at": order.created_at,
            }
            if status_name == "requested":
                incoming_requests.append(data)
            elif status_name in ["confirmed", "active", "overdue", "unreturned"]:
                ongoing.append(data)
            elif status_name in [
                "returned",
                "completed",
                "declined",
                "expired",
                "cancelled",
                "disputed",
            ]:
                past.append(data)
            else:
                past.append(data)
        return Response(
            {
                "user": UserResponseSerializer(user, context={"request": request}).data,
                "listings": listings_data,
                "incoming_requests": incoming_requests,
                "ongoing_lends": ongoing,
                "past_orders": past,
            },
            status=status.HTTP_200_OK,
        )
