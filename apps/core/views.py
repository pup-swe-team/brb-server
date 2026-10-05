from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.users.services import (
    deactivate_unverified_users,
    email_verification_expiry_days,
)

from .cron import CronSecretMixin


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
