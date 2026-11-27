"""Admin-only DRF API views for dashboard metrics (CP-1107) and review queues (CP-1103)."""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.codes.views import _extract_uploaded_evidence_files
from apps.reports.serializers import serialize_report
from apps.reports.services import list_reports, resolve_report

from .admin_queues import (
    get_admin_review_queues,
    list_admin_verifications,
    perform_review_queue_action,
)
from .admin_selectors import get_admin_dashboard_metrics


class AdminMetricsView(APIView):
    """
    GET /api/v1/admin/metrics/
    GET /api/v1/admin/dashboard/metrics/
    Admin-only platform metrics aggregation endpoint (CP-1107).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request) -> Response:
        metrics = get_admin_dashboard_metrics()
        return Response(metrics, status=status.HTTP_200_OK)


class AdminReviewQueueListView(APIView):
    """
    GET /api/v1/admin/review-queues/
    Admin-only aggregated queue across Verification, Reports, and Unreturned Cases (CP-1103).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request) -> Response:
        queue_type = request.query_params.get("type", "all")
        status_filter = request.query_params.get("status", "open")
        payload = get_admin_review_queues(
            queue_type=queue_type,
            status_filter=status_filter,
        )
        return Response(payload, status=status.HTTP_200_OK)


class AdminReviewQueueActionView(APIView):
    """
    POST /api/v1/admin/review-queues/<str:queue_type>/<int:pk>/action/
    Admin-only unified action persistence endpoint for Verification, Reports, and Unreturned Cases (CP-1103).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request: Request, queue_type: str, pk: int) -> Response:
        action = request.data.get("action", "")
        evidence_files = _extract_uploaded_evidence_files(request)
        result = perform_review_queue_action(
            queue_type=queue_type,
            item_id=pk,
            admin=request.user,
            action=action,
            data=request.data,
            evidence_files=evidence_files,
            request=request,
        )
        return Response(result, status=status.HTTP_200_OK)


class AdminVerificationListView(APIView):
    """
    GET /api/v1/admin/verifications/
    Admin-only list of identity verification submissions (`?status=pending|approved|rejected|all`) (CP-1103).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status", "pending")
        items = list_admin_verifications(status_filter=status_filter)
        return Response(items, status=status.HTTP_200_OK)


class AdminReportListView(APIView):
    """
    GET /api/v1/admin/reports/
    Admin-only list of reports across User, Listing, Review, and Message tables (CP-1103).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request) -> Response:
        report_type = request.query_params.get("type", "all")
        status_filter = request.query_params.get("status", "open")
        items = list_reports(report_type=report_type, status_filter=status_filter)
        return Response(items, status=status.HTTP_200_OK)


class AdminReportResolveView(APIView):
    """
    POST /api/v1/admin/reports/<str:report_type>/<int:pk>/resolve/
    Admin-only report resolution persistence endpoint (CP-1103).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request: Request, report_type: str, pk: int) -> Response:
        notes = (
            request.data.get("resolution_notes") or request.data.get("notes") or ""
        ).strip()
        report = resolve_report(
            report_type=report_type,
            report_id=pk,
            admin=request.user,
            resolution_notes=notes,
        )
        return Response(serialize_report(report), status=status.HTTP_200_OK)
