from django.core.paginator import Paginator
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AdminAccessLog
from .serializers import AdminAccessLogSerializer


class AdminAuditLogListView(APIView):
    """
    CP-1106 / FR14 / TC-115: Read-only list of immutable admin audit log entries.
    Supports filtering by action, target_type, admin, and search query.
    """

    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        qs = AdminAccessLog.objects.select_related("admin", "document").order_by(
            "-accessed_at"
        )

        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)

        target_type = request.query_params.get("target_type")
        if target_type:
            qs = qs.filter(target_type=target_type)

        admin_id = request.query_params.get("admin_id")
        if admin_id and admin_id.isdigit():
            qs = qs.filter(admin_id=int(admin_id))

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(admin__email__icontains=search)
                | Q(admin__full_name__icontains=search)
                | Q(action__icontains=search)
                | Q(target_id__icontains=search)
                | Q(details__icontains=search)
            )

        page_number = request.query_params.get("page", 1)
        page_size = min(int(request.query_params.get("page_size", 25)), 100)

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.get_page(page_number)
        except Exception:  # noqa: BLE001
            page = paginator.get_page(1)

        serializer = AdminAccessLogSerializer(page.object_list, many=True)
        return Response(
            {
                "count": paginator.count,
                "num_pages": paginator.num_pages,
                "current_page": page.number,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminAuditLogDetailView(APIView):
    """
    CP-1106 / FR14 / TC-116: Read-only detail view for an audit log entry.
    All modifying methods (PUT, PATCH, DELETE) are forbidden.
    """

    permission_classes = (IsAdminUser,)

    def get(self, request: Request, pk: int) -> Response:
        try:
            log = AdminAccessLog.objects.select_related("admin", "document").get(pk=pk)
        except AdminAccessLog.DoesNotExist:
            return Response(
                {"error": "Audit log entry not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdminAccessLogSerializer(log)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request: Request, pk: int) -> Response:
        return Response(
            {"error": "Audit log entries are immutable and cannot be modified."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def patch(self, request: Request, pk: int) -> Response:
        return Response(
            {"error": "Audit log entries are immutable and cannot be modified."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def delete(self, request: Request, pk: int) -> Response:
        return Response(
            {"error": "Audit log entries are immutable and cannot be deleted."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
