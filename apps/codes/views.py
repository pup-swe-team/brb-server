"""Views for handover and return authentication codes (CP-504, CP-505)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    AuthCodeResponseSerializer,
    HandoverCodeVerifyInputSerializer,
    HandoverVerificationResponseSerializer,
    ReturnCodeVerifyInputSerializer,
    ReturnVerificationResponseSerializer,
)
from .services import (
    generate_handover_code,
    generate_return_code,
    verify_handover_code,
    verify_return_code,
)


def _extract_uploaded_evidence_files(request: Request) -> list:
    """Collect any uploaded evidence files from multipart request.FILES."""
    if not hasattr(request, "FILES") or not request.FILES:
        return []
    files = []
    for key in ("evidence", "evidences", "evidence[]", "files", "photos"):
        if key in request.FILES:
            files.extend(request.FILES.getlist(key))
    return files


class GenerateHandoverCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/handover-code/generate/
    Lender generates a single-use 6-digit OTP for a Confirmed order ready for handover (CP-504).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, order_id: int) -> Response:
        auth_code = generate_handover_code(order_id=order_id, actor=request.user)
        return Response(
            AuthCodeResponseSerializer(auth_code).data,
            status=status.HTTP_201_CREATED,
        )


class VerifyHandoverCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/handover-code/verify/
    Borrower validates the Lender's handover code to transition the order to Active (CP-504).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, order_id: int) -> Response:
        serializer = HandoverCodeVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, consumed_code = verify_handover_code(
            order_id=order_id,
            actor=request.user,
            code_value=serializer.validated_data["code"],
        )
        order.auth_code = consumed_code
        return Response(
            HandoverVerificationResponseSerializer(order).data,
            status=status.HTTP_200_OK,
        )


class GenerateReturnCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/return-code/generate/
    Borrower generates a single-use 6-digit OTP on return initiation (CP-505).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, order_id: int) -> Response:
        auth_code = generate_return_code(order_id=order_id, actor=request.user)
        return Response(
            AuthCodeResponseSerializer(auth_code).data,
            status=status.HTTP_201_CREATED,
        )


class VerifyReturnCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/return-code/verify/
    Lender validates the Borrower's return code to mark the order Returned and
    automatically set Completed (unflagged) or Disputed (flagged) (CP-505).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, order_id: int) -> Response:
        serializer = ReturnCodeVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        evidence_files = _extract_uploaded_evidence_files(request)
        order, consumed_code, dispute = verify_return_code(
            order_id=order_id,
            actor=request.user,
            code_value=serializer.validated_data["code"],
            flagged=serializer.validated_data["flagged"],
            dispute_description=serializer.validated_data["dispute_description"],
            evidence_files=evidence_files,
        )
        order.auth_code = consumed_code
        order.returned_status = "returned"
        order.dispute_id = dispute.pk if dispute is not None else None
        return Response(
            ReturnVerificationResponseSerializer(order).data,
            status=status.HTTP_200_OK,
        )
