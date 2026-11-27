from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.services import (
    expire_unanswered_requests,
    process_overdue_and_unreturned_orders,
    request_expiry_hours,
)
from apps.reports.services import auto_flag_repeatedly_reported_users
from apps.users.services import (
    deactivate_unverified_users,
    email_verification_expiry_days,
)

from .cron import CronSecretMixin


class HealthView(APIView):
    """
    Liveness probe for Render's health checks (no auth, no DB access).

    GET /healthz/ -- must answer 200 quickly so the platform does not restart
    the instance; deliberately avoids touching the database so a sleeping
    Postgres does not turn a healthy app into a failed check.
    """

    authentication_classes = ()
    permission_classes = ()

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class DeactivateUnverifiedAccountsView(CronSecretMixin):
    """
    Remove accounts that never confirmed their email (CP-102).

    POST /api/v1/jobs/deactivate-unverified/ -- called by cron-job.org daily.

    The endpoint is named for the work it does rather than reusing the
    `/jobs/check-overdue/` path from the sprint doc, because that one belongs to
    CP-506's overdue/unreturned sweep and there is nothing overdue here yet.
    Both are scheduled jobs on the same secret and can share a cron schedule
    later.
    """

    authentication_classes = ()
    permission_classes = ()

    def post(self, request: Request) -> Response:
        error_response = self.verify_cron_secret(request)
        if error_response is not None:
            return error_response

        deactivated_ids = deactivate_unverified_users()

        return Response(
            {
                "job": "deactivate-unverified",
                "expiry_days": email_verification_expiry_days(),
                "deactivated_count": len(deactivated_ids),
                "deactivated_user_ids": deactivated_ids,
                "executed_at": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class ExpireBorrowRequestsView(CronSecretMixin):
    """Expire unanswered borrow requests after the configured deadline."""

    authentication_classes = ()
    permission_classes = ()

    def post(self, request: Request) -> Response:
        error_response = self.verify_cron_secret(request)
        if error_response is not None:
            return error_response

        expired_ids = expire_unanswered_requests()
        return Response(
            {
                "job": "expire-borrow-requests",
                "expiry_hours": request_expiry_hours(),
                "expired_count": len(expired_ids),
                "expired_order_ids": expired_ids,
                "executed_at": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class CheckOverdueOrdersView(CronSecretMixin):
    """
    Scheduled sweep for overdue and unreturned orders + expired auth codes (CP-506, CP-504/505).

    POST /api/v1/jobs/check-overdue/ -- called by cron-job.org on a schedule with
    `CRON_SECRET_TOKEN` in the `Authorization` header (DECISIONS.md D-01).
    """

    authentication_classes = ()
    permission_classes = ()

    def post(self, request: Request) -> Response:
        error_response = self.verify_cron_secret(request)
        if error_response is not None:
            return error_response

        now = timezone.now()
        summary = process_overdue_and_unreturned_orders(now=now)
        return Response(
            {
                "job": "check-overdue",
                **summary,
                "executed_at": now.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class AutoFlagRepeatedlyReportedUsersJobView(CronSecretMixin):
    """
    Scheduled sweep to automatically flag users with 3+ reports in rolling 30 days (CP-902).

    POST /api/v1/jobs/auto-flag-users/ -- leaves account unrestricted until an Admin
    confirms the flag.
    """

    authentication_classes = ()
    permission_classes = ()

    def post(self, request: Request) -> Response:
        error_response = self.verify_cron_secret(request)
        if error_response is not None:
            return error_response

        summary = auto_flag_repeatedly_reported_users()
        return Response(
            {
                "job": "auto-flag-users",
                **summary,
            },
            status=status.HTTP_200_OK,
        )


class AdminSystemConfigListView(APIView):
    """
    CP-1104 / FR14: Read and bulk-update platform runtime configuration parameters.
    Only accessible by staff/administrators (D-03).
    """

    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        from .constants import CONFIG_METADATA
        from .models import SystemConfig

        db_configs = {
            c.config_key: c
            for c in SystemConfig.objects.select_related("updated_by").all()
        }

        category_filter = request.query_params.get("category")

        items = []
        for key, meta in CONFIG_METADATA.items():
            if category_filter and meta.get("category") != category_filter:
                continue
            row = db_configs.get(key)
            val = row.config_value if row else str(meta["default"])
            items.append(
                {
                    "config_key": key,
                    "config_value": val,
                    "label": meta["label"],
                    "category": meta["category"],
                    "description": meta["description"],
                    "type": meta["type"],
                    "default_value": str(meta["default"]),
                    "min_value": meta.get("min"),
                    "max_value": meta.get("max"),
                    "updated_by": (
                        row.updated_by.email if (row and row.updated_by) else None
                    ),
                    "updated_at": row.updated_at if row else None,
                }
            )

        return Response({"configs": items}, status=status.HTTP_200_OK)

    def put(self, request: Request) -> Response:
        from .constants import CONFIG_METADATA
        from .models import SystemConfig
        from .serializers import SystemConfigBulkUpdateSerializer

        serializer = SystemConfigBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_configs = serializer.validated_data["configs"]

        updated_items = []
        for key, val in validated_configs.items():
            row, _ = SystemConfig.objects.update_or_create(
                config_key=key,
                defaults={
                    "config_value": val,
                    "updated_by": request.user,
                },
            )
            meta = CONFIG_METADATA[key]
            updated_items.append(
                {
                    "config_key": key,
                    "config_value": row.config_value,
                    "label": meta["label"],
                    "category": meta["category"],
                    "description": meta["description"],
                    "type": meta["type"],
                    "default_value": str(meta["default"]),
                    "min_value": meta.get("min"),
                    "max_value": meta.get("max"),
                    "updated_by": request.user.email,
                    "updated_at": row.updated_at,
                }
            )

        return Response(
            {
                "message": f"Successfully updated {len(updated_items)} configuration parameters.",
                "configs": updated_items,
            },
            status=status.HTTP_200_OK,
        )


class AdminSystemConfigDetailView(APIView):
    """
    CP-1104 / FR14: Read or update a specific platform runtime configuration parameter.
    Only accessible by staff/administrators (D-03).
    """

    permission_classes = (IsAdminUser,)

    def get(self, request: Request, key: str) -> Response:
        from .constants import CONFIG_METADATA
        from .models import SystemConfig

        if key not in CONFIG_METADATA:
            return Response(
                {"error": f"Configuration key '{key}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        meta = CONFIG_METADATA[key]
        try:
            row = SystemConfig.objects.select_related("updated_by").get(config_key=key)
            val = row.config_value
            updated_by = row.updated_by.email if row.updated_by else None
            updated_at = row.updated_at
        except SystemConfig.DoesNotExist:
            val = str(meta["default"])
            updated_by = None
            updated_at = None

        return Response(
            {
                "config_key": key,
                "config_value": val,
                "label": meta["label"],
                "category": meta["category"],
                "description": meta["description"],
                "type": meta["type"],
                "default_value": str(meta["default"]),
                "min_value": meta.get("min"),
                "max_value": meta.get("max"),
                "updated_by": updated_by,
                "updated_at": updated_at,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request: Request, key: str) -> Response:
        return self._update(request, key)

    def put(self, request: Request, key: str) -> Response:
        return self._update(request, key)

    def _update(self, request: Request, key: str) -> Response:
        from .constants import CONFIG_METADATA
        from .models import SystemConfig
        from .serializers import SystemConfigUpdateSerializer

        if key not in CONFIG_METADATA:
            return Response(
                {"error": f"Configuration key '{key}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        meta = CONFIG_METADATA[key]
        serializer = SystemConfigUpdateSerializer(
            data=request.data,
            context={"config_key": key},
        )
        serializer.is_valid(raise_exception=True)
        val = serializer.validated_data["value"]

        row, _ = SystemConfig.objects.update_or_create(
            config_key=key,
            defaults={
                "config_value": val,
                "updated_by": request.user,
            },
        )

        return Response(
            {
                "message": f"Configuration parameter '{key}' updated successfully.",
                "config_key": key,
                "config_value": row.config_value,
                "label": meta["label"],
                "category": meta["category"],
                "description": meta["description"],
                "type": meta["type"],
                "default_value": str(meta["default"]),
                "min_value": meta.get("min"),
                "max_value": meta.get("max"),
                "updated_by": request.user.email,
                "updated_at": row.updated_at,
            },
            status=status.HTTP_200_OK,
        )
