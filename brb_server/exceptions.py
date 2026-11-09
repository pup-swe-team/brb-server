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
        elif isinstance(response.data, dict):
            if "code" not in response.data:
                if isinstance(codes, dict):
                    first_key = next(iter(codes), None)
                    if first_key and codes[first_key]:
                        val = codes[first_key]
                        response.data["code"] = (
                            val[0] if isinstance(val, list) else str(val)
                        )
                elif hasattr(exc, "default_code") and exc.default_code:
                    response.data["code"] = exc.default_code

            # Ensure structured top-level detail string is present for clients
            if "detail" not in response.data:
                if response.data.get("non_field_errors"):
                    nfe = response.data["non_field_errors"]
                    response.data["detail"] = (
                        nfe[0] if isinstance(nfe, list) else str(nfe)
                    )
                else:
                    first_val = next(iter(response.data.values()), None)
                    if (
                        first_val
                        and isinstance(first_val, (list, tuple))
                        and len(first_val) > 0
                    ):
                        response.data["detail"] = str(first_val[0])
                    elif isinstance(first_val, str):
                        response.data["detail"] = first_val
    return response
