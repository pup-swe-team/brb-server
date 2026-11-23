"""Views for handover and return authentication codes (CP-504, CP-505)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import ValidationError
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
    get_order_code_info,
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


def _resolve_order_id(request: Request, order_id: int | None = None) -> int:
    """Resolve order_id either from URL kwargs, query params, or JSON request body."""
    if order_id is not None:
        return int(order_id)
    val = request.query_params.get("order_id")
    if val is None and hasattr(request, "data"):
        val = request.data.get("order_id")
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    raise ValidationError({"order_id": "A valid order_id is required."})


class GenerateHandoverCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/handover-code/generate/
    GET  /api/v1/orders/<int:order_id>/handover-code/generate/
    Lender generates or inspects a single-use 6-digit OTP for a Confirmed order ready for handover (CP-504).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        info = get_order_code_info(
            order_id=oid, actor=request.user, code_type_name="handover"
        )
        return Response(info, status=status.HTTP_200_OK)

    def post(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        reuse_existing = request.query_params.get("reuse_existing") in (
            "true",
            "1",
        ) or bool(
            getattr(request, "data", None)
            and request.data.get("reuse_existing") in ("true", "1", True)
        )
        auth_code = generate_handover_code(
            order_id=oid,
            actor=request.user,
            force_new=not reuse_existing,
        )
        return Response(
            AuthCodeResponseSerializer(auth_code).data,
            status=status.HTTP_201_CREATED,
        )


class VerifyHandoverCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/handover-code/verify/
    GET  /api/v1/orders/<int:order_id>/handover-code/verify/
    Borrower validates or inspects lockout status for the handover code (CP-504).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        info = get_order_code_info(
            order_id=oid, actor=request.user, code_type_name="handover"
        )
        return Response(info, status=status.HTTP_200_OK)

    def post(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        serializer = HandoverCodeVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, consumed_code = verify_handover_code(
            order_id=oid,
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
    GET  /api/v1/orders/<int:order_id>/return-code/generate/
    Borrower generates or inspects a single-use 6-digit OTP on return initiation (CP-505).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        info = get_order_code_info(
            order_id=oid, actor=request.user, code_type_name="return"
        )
        return Response(info, status=status.HTTP_200_OK)

    def post(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        reuse_existing = request.query_params.get("reuse_existing") in (
            "true",
            "1",
        ) or bool(
            getattr(request, "data", None)
            and request.data.get("reuse_existing") in ("true", "1", True)
        )
        auth_code = generate_return_code(
            order_id=oid,
            actor=request.user,
            force_new=not reuse_existing,
        )
        return Response(
            AuthCodeResponseSerializer(auth_code).data,
            status=status.HTTP_201_CREATED,
        )


class VerifyReturnCodeView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/return-code/verify/
    GET  /api/v1/orders/<int:order_id>/return-code/verify/
    Lender validates the Borrower's return code or inspects lockout status (CP-505).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        info = get_order_code_info(
            order_id=oid, actor=request.user, code_type_name="return"
        )
        return Response(info, status=status.HTTP_200_OK)

    def post(self, request: Request, order_id: int | None = None) -> Response:
        oid = _resolve_order_id(request, order_id)
        serializer = ReturnCodeVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        evidence_files = _extract_uploaded_evidence_files(request)
        order, consumed_code, dispute = verify_return_code(
            order_id=oid,
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
