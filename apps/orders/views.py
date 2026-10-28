from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsIdentityVerified

from .serializers import BorrowRequestResultSerializer, BorrowRequestSerializer
from .services import request_borrow, respond_to_borrow_request


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
