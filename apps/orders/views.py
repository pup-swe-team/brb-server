from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsIdentityVerified

from .models import Order
from .serializers import (
    BorrowRequestResultSerializer,
    BorrowRequestSerializer,
    CancelOrderSerializer,
    OrderDetailSerializer,
)
from .services import cancel_order, request_borrow, respond_to_borrow_request


class BorrowRequestView(APIView):
    permission_classes = (IsAuthenticated, IsIdentityVerified)

    def post(self, request):
        serializer = BorrowRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = request_borrow(borrower=request.user, **serializer.validated_data)
        return Response(
            BorrowRequestResultSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class BorrowRequestResponseView(APIView):
    permission_classes = (IsAuthenticated,)
    action = ""

    def post(self, request, pk: int):
        order, outcome = respond_to_borrow_request(
            lender=request.user, order_id=pk, action=self.action
        )
        return Response(
            BorrowRequestResultSerializer(order).data,
            status=(
                status.HTTP_409_CONFLICT if outcome == "expired" else status.HTTP_200_OK
            ),
        )


class AcceptBorrowRequestView(BorrowRequestResponseView):
    action = "accept"


class DeclineBorrowRequestView(BorrowRequestResponseView):
    action = "decline"


class OrderDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, pk: int):
        order = get_object_or_404(
            Order.objects.select_related("listing", "status"), pk=pk
        )
        if request.user.pk not in (order.borrower_id, order.listing.lender_id):
            raise PermissionDenied("Only the borrower or lender can view this order.")
        return Response(OrderDetailSerializer(order).data)


class CancelOrderView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, pk: int):
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = cancel_order(
            actor=request.user, order_id=pk, reason=serializer.validated_data["reason"]
        )
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_200_OK)
