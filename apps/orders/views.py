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
    expire_unanswered_requests,
    override_order_status,
    process_overdue_and_unreturned_orders,
    request_borrow,
    respond_to_borrow_request,
    sync_order_time_derived_status,
)


class BorrowRequestView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        role = (request.query_params.get("role") or "").strip().lower()
        expire_unanswered_requests()
        process_overdue_and_unreturned_orders()
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
        return Response(
            OrderDetailSerializer(orders, many=True, context={"request": request}).data
        )

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
        order = sync_order_time_derived_status(order)
        return Response(OrderDetailSerializer(order, context={"request": request}).data)


class CancelOrderView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, pk: int):
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = cancel_order(
            actor=request.user, order_id=pk, reason=serializer.validated_data["reason"]
        )
        return Response(
            OrderDetailSerializer(order, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


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


class DamageReportView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/damage-report/
    GET  /api/v1/orders/<int:order_id>/damage-report/
    Lender or borrower submits or retrieves damage report and evidence (CP-505).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int) -> Response:
        order = get_object_or_404(Order.objects.select_related("listing"), pk=order_id)
        if (
            request.user.pk not in (order.borrower_id, order.listing.lender_id)
            and not request.user.is_staff
        ):
            raise PermissionDenied(
                "Only the order parties or admin can view this damage report."
            )
        from .models import Dispute

        dispute = Dispute.objects.filter(order=order).order_by("-created_at").first()
        if dispute is None:
            return Response(
                {"detail": "No damage report found for this order."},
                status=status.HTTP_404_NOT_FOUND,
            )
        from .serializers import DisputeDetailSerializer

        return Response(
            DisputeDetailSerializer(dispute, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request, order_id: int) -> Response:
        order = get_object_or_404(
            Order.objects.select_related("listing", "status"), pk=order_id
        )
        if request.user.pk not in (order.borrower_id, order.listing.lender_id):
            raise PermissionDenied("Only the order parties can submit a damage report.")

        description = (
            request.data.get("description")
            or request.data.get("dispute_description")
            or ""
        ).strip()
        if not description:
            return Response(
                {"description": ["A description of the damage is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.codes.services import _infer_evidence_file_type

        from .models import Dispute, DisputeEvidence, OrderStatus

        # Transition order to disputed status
        disputed_status, _ = OrderStatus.objects.get_or_create(name="disputed")
        order.status = disputed_status
        order.save(update_fields=["status", "updated_at"])

        dispute = Dispute.objects.filter(order=order).order_by("-created_at").first()
        if dispute is None:
            dispute = Dispute.objects.create(
                order=order,
                raised_by=request.user,
                description=description,
                status=Dispute.StatusChoices.OPEN,
            )
        else:
            dispute.description = description
            dispute.save(update_fields=["description", "updated_at"])

        evidence_files = _extract_uploaded_evidence_files(request)
        for f in evidence_files:
            ft = _infer_evidence_file_type(f)
            DisputeEvidence.objects.create(
                dispute=dispute,
                submitted_by=request.user,
                file_reference=f,
                file_type=ft,
            )

        from .serializers import DisputeDetailSerializer

        return Response(
            DisputeDetailSerializer(dispute, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class AdminDisputeListView(APIView):
    """
    GET /api/v1/disputes/
    Admin-only listing of all damage disputes (CP-505, CP-506).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        from .models import Dispute
        from .serializers import DisputeDetailSerializer

        qs = (
            Dispute.objects.select_related(
                "order",
                "order__listing",
                "order__listing__lender",
                "order__borrower",
                "order__status",
                "raised_by",
                "resolved_by",
            )
            .prefetch_related("evidences", "evidences__file_type")
            .order_by("-created_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.strip().lower())

        return Response(
            DisputeDetailSerializer(qs, many=True, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class AdminDisputeDetailView(APIView):
    """
    GET /api/v1/disputes/<int:pk>/
    Admin-only review dossier for a damage dispute, matching AdminCase format.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request, pk: int) -> Response:
        from .models import Dispute

        dispute = get_object_or_404(
            Dispute.objects.select_related(
                "order",
                "order__listing",
                "order__listing__category",
                "order__listing__pickup_location",
                "order__listing__lender",
                "order__borrower",
                "order__status",
                "raised_by",
                "resolved_by",
            ).prefetch_related("evidences", "evidences__file_type"),
            pk=pk,
        )
        order = dispute.order
        listing = order.listing
        borrower = order.borrower
        lender = listing.lender

        evidences_data = []
        for ev in dispute.evidences.all():
            url = ev.file_reference.url if ev.file_reference else ""
            if url and not url.startswith("http"):
                url = request.build_absolute_uri(url)
            evidences_data.append(
                {
                    "id": ev.id,
                    "file_url": url,
                    "file_type": ev.file_type.name if ev.file_type else "photo",
                    "uploaded_at": ev.uploaded_at.isoformat(),
                }
            )

        dossier = {
            "case": {
                "id": dispute.pk,
                "dispute_id": dispute.pk,
                "order_id": order.pk,
                "type": "damage_dispute",
                "status": dispute.status,
                "description": dispute.description,
                "resolution_notes": dispute.resolution_notes or "",
                "created_at": dispute.created_at.isoformat(),
                "updated_at": dispute.updated_at.isoformat(),
            },
            "order": {
                "id": order.pk,
                "status": order.status.name,
                "start_date": str(order.start_date),
                "end_date": str(order.end_date),
            },
            "listing": {
                "id": listing.pk,
                "title": listing.title,
                "category": getattr(listing.category, "name", ""),
                "pickup_location": getattr(listing.pickup_location, "name", ""),
            },
            "borrower": {
                "id": borrower.pk,
                "full_name": borrower.full_name,
                "email": borrower.email,
                "contact_number": borrower.contact_number,
            },
            "lender": {
                "id": lender.pk,
                "full_name": lender.full_name,
                "email": lender.email,
                "contact_number": lender.contact_number,
            },
            "evidences": evidences_data,
            "events": [
                {
                    "id": "e1",
                    "label": "Dispute reported",
                    "date": dispute.created_at.strftime("%Y-%m-%d"),
                },
            ],
        }
        if dispute.resolution_notes:
            dossier["events"].append(
                {
                    "id": "e2",
                    "label": f"Resolution: {dispute.resolution_notes}",
                    "date": dispute.updated_at.strftime("%Y-%m-%d"),
                }
            )
        return Response(dossier, status=status.HTTP_200_OK)


class AdminDisputeResolveView(APIView):
    """
    POST /api/v1/disputes/<int:pk>/resolve/
    Admin marks damage dispute resolved and transitions order to completed.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        from apps.listings.services import release_dates_for_order

        from .models import Dispute, OrderStatus

        dispute = get_object_or_404(Dispute.objects.select_related("order"), pk=pk)
        notes = (
            request.data.get("resolution_notes")
            or request.data.get("notes")
            or "Resolved by admin"
        ).strip()
        dispute.status = Dispute.StatusChoices.RESOLVED
        dispute.resolved_by = request.user
        dispute.resolution_notes = notes
        dispute.save(
            update_fields=["status", "resolved_by", "resolution_notes", "updated_at"]
        )

        completed_status, _ = OrderStatus.objects.get_or_create(name="completed")
        dispute.order.status = completed_status
        dispute.order.save(update_fields=["status", "updated_at"])
        release_dates_for_order(dispute.order)

        return Response(
            {"message": "Dispute resolved successfully.", "status": "resolved"},
            status=status.HTTP_200_OK,
        )


class AdminDisputeEscalateView(APIView):
    """
    POST /api/v1/disputes/<int:pk>/escalate/
    Admin escalates damage dispute for administrative or disciplinary review.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        from .models import Dispute

        dispute = get_object_or_404(Dispute.objects.select_related("order"), pk=pk)
        notes = (
            request.data.get("resolution_notes")
            or request.data.get("notes")
            or "Escalated for administrative review"
        ).strip()
        dispute.status = Dispute.StatusChoices.ESCALATED
        dispute.resolution_notes = notes
        dispute.save(update_fields=["status", "resolution_notes", "updated_at"])

        return Response(
            {"message": "Dispute escalated successfully.", "status": "escalated"},
            status=status.HTTP_200_OK,
        )
