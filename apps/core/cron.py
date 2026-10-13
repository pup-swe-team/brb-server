"""Shared plumbing for cron-job.org-triggered endpoints.

SRS Section 2.4 / 5.2 and CONTRIBUTING.md 7.2 rule 6: scheduled-job endpoints
must require the shared `CRON_SECRET_TOKEN` and answer `401 Unauthorized` to
anything else. D-01 confirms the team drives these from cron-job.org.
"""

import secrets

from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class CronSecretMixin(APIView):
    """
    Base view that enforces the shared scheduled-job secret.

    Subclasses call `verify_cron_secret(request)` first and return early on the
    error response. `AllowAny` is deliberate and does not weaken anything: the
    token check here *is* the authentication, and DRF has no permission class
    that compares a header value against a secret.
    """

    permission_classes = ()

    def verify_cron_secret(self, request: Request) -> Response | None:
        """Return an error Response to stop the job, or None to let it run."""
        configured_token = (getattr(settings, "CRON_SECRET_TOKEN", "") or "").strip()
        if not configured_token:
            # Refuse to run rather than accept everything. An unset secret is a
            # deployment mistake, and silently accepting every caller would turn
            # one missing env var into an open endpoint.
            return Response(
                {"detail": "Scheduled job secret is not configured on the server."},
                status=503,
            )

        header_value = request.headers.get("Authorization", "")
        # cron-job.org can be configured to send the bare token; `Bearer ` is
        # accepted too so the same header works from curl or a mobile client.
        presented_token = header_value.removeprefix("Bearer ").strip()

        if not presented_token or not secrets.compare_digest(
            presented_token.encode("utf-8"), configured_token.encode("utf-8")
        ):
            return Response(
                {"detail": "Invalid or missing scheduled job secret."},
                status=401,
            )

        return None
