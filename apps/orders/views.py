"""Views for order lifecycle (CP-501, CP-502, CP-503) and unreturned cases/status overrides (CP-506)."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.codes.views import _extract_uploaded_evidence_files

from .models import Order
from .selectors import get_unreturned_case_dossier, list_unreturned_cases
from .serializers import (
    BorrowRequestResultSerializer,
    BorrowRequestSerializer,
    CancelOrderSerializer,
    CloseUnreturnedCaseSerializer,
    EscalateUnreturnedCaseSerializer,
    OrderDetailSerializer,
    OrderStatusOverrideInputSerializer,
    OrderStatusOverrideResultSerializer,
    UnreturnedCaseSummarySerializer,
)
from .services import (
    cancel_order,
    close_unreturned_case,
    escalate_unreturned_case,
    override_order_status,
    request_borrow,
    respond_to_borrow_request,
)


class BorrowRequestView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        role = (request.query_params.get("role") or "").strip().lower()
        queryset = Order.objects.select_related(
            "listing",
            "listing__pickup_location",
            "listing__lender",
            "borrower",
            "status",
        ).order_by("-created_at")
        if role in ("borrower",):
            orders = queryset.filter(borrower=request.user)
        elif role in ("lender",):
            orders = queryset.filter(listing__lender=request.user)
        else:
            orders = queryset.filter(
                Q(borrower=request.user) | Q(listing__lender=request.user)
            )
        return Response(OrderDetailSerializer(orders, many=True).data)

    def post(self, request):
        if not request.user.has_verified_identity():
            raise PermissionDenied("Identity verification required to borrow items.")
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
            Order.objects.select_related(
                "listing",
                "listing__pickup_location",
                "listing__lender",
                "borrower",
                "status",
            ),
            pk=pk,
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


class UnreturnedCaseListView(APIView):
    """
    GET /api/v1/unreturned-cases/
    Admin-only list of UnreturnedCase records, optionally filtered by `?status=open|escalated|returned|unresolved`.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status")
        cases = list_unreturned_cases(status_filter=status_filter)
        return Response(
            UnreturnedCaseSummarySerializer(cases, many=True).data,
            status=status.HTTP_200_OK,
        )


class UnreturnedCaseDetailView(APIView):
    """
    GET /api/v1/unreturned-cases/<int:pk>/
    Admin-only review dossier linking identity, contact, order, chat, code attempts, and evidence (CP-506).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request, pk: int) -> Response:
        dossier = get_unreturned_case_dossier(
            case_id=pk,
            admin=request.user,
            request=request,
        )
        return Response(dossier, status=status.HTTP_200_OK)


class EscalateUnreturnedCaseView(APIView):
    """
    POST /api/v1/unreturned-cases/<int:pk>/escalate/
    Admin escalates an UnreturnedCase to PUP OSS / Campus Security with attached evidence and notes (CP-506).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = EscalateUnreturnedCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        evidence_files = _extract_uploaded_evidence_files(request)
        case = escalate_unreturned_case(
            case_id=pk,
            admin=request.user,
            resolution_notes=serializer.validated_data["resolution_notes"],
            evidence_files=evidence_files,
        )
        dossier = get_unreturned_case_dossier(
            case_id=case.pk,
            admin=request.user,
            request=request,
        )
        return Response(dossier, status=status.HTTP_200_OK)


class CloseUnreturnedCaseView(APIView):
    """
    POST /api/v1/unreturned-cases/<int:pk>/close/
    Admin closes an UnreturnedCase as 'returned' or 'unresolved' with resolution notes (CP-506).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = CloseUnreturnedCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        case = close_unreturned_case(
            case_id=pk,
            admin=request.user,
            close_status=serializer.validated_data["status"],
            resolution_notes=serializer.validated_data["resolution_notes"],
        )
        dossier = get_unreturned_case_dossier(
            case_id=case.pk,
            admin=request.user,
            request=request,
        )
        return Response(dossier, status=status.HTTP_200_OK)


class OrderStatusOverrideView(APIView):
    """
    POST /api/v1/orders/<int:pk>/override-status/
    Admin manual order status correction with a recorded reason (CP-506, FR8, FR14).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = OrderStatusOverrideInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, override_record = override_order_status(
            order_id=pk,
            admin=request.user,
            new_status=serializer.validated_data["new_status"],
            reason=serializer.validated_data["reason"],
        )
        order.override = override_record
        return Response(
            OrderStatusOverrideResultSerializer(order).data,
            status=status.HTTP_200_OK,
        )
