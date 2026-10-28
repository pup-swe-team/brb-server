from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsIdentityVerified

from .serializers import BorrowRequestResultSerializer, BorrowRequestSerializer
from .services import request_borrow


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
