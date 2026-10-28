from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.services import expire_unanswered_requests, request_expiry_hours
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
