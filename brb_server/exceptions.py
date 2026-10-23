"""Project-wide DRF exception handler.

The client branches on machine-readable error ``code`` values (e.g.
``unverified_email`` at login). DRF's default handler only emits ``detail``, so
the documented contract in ``LoginSerializer`` never reached the wire. This
handler keeps DRF's default behaviour and adds ``code`` for every
``APIException`` whose ``detail`` is a plain string.
"""

from rest_framework import exceptions as drf_exceptions
from rest_framework.views import exception_handler as drf_views_exception_handler


def api_exception_handler(exc, context):
    response = drf_views_exception_handler(exc, context)
    if response is not None and isinstance(exc, drf_exceptions.APIException):
        codes = exc.get_codes()
        if isinstance(codes, str) and codes:
            response.data["code"] = codes
    return response
