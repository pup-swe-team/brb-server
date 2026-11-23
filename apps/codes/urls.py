"""URL routes for authentication code generation and verification (CP-504, CP-505)."""

from django.urls import path

from .views import (
    GenerateHandoverCodeView,
    GenerateReturnCodeView,
    VerifyHandoverCodeView,
    VerifyReturnCodeView,
)

urlpatterns = [
    path(
        "orders/<int:order_id>/handover-code/",
        GenerateHandoverCodeView.as_view(),
        name="order-handover-code-status",
    ),
    path(
        "orders/<int:order_id>/handover-code/generate/",
        GenerateHandoverCodeView.as_view(),
        name="order-handover-code-generate",
    ),
    path(
        "orders/<int:order_id>/handover-code/verify/",
        VerifyHandoverCodeView.as_view(),
        name="order-handover-code-verify",
    ),
    path(
        "orders/<int:order_id>/return-code/",
        GenerateReturnCodeView.as_view(),
        name="order-return-code-status",
    ),
    path(
        "orders/<int:order_id>/return-code/generate/",
        GenerateReturnCodeView.as_view(),
        name="order-return-code-generate",
    ),
    path(
        "orders/<int:order_id>/return-code/verify/",
        VerifyReturnCodeView.as_view(),
        name="order-return-code-verify",
    ),
    path(
        "codes/generate-handover/",
        GenerateHandoverCodeView.as_view(),
        name="codes-generate-handover",
    ),
    path(
        "codes/verify-handover/",
        VerifyHandoverCodeView.as_view(),
        name="codes-verify-handover",
    ),
    path(
        "codes/generate-return/",
        GenerateReturnCodeView.as_view(),
        name="codes-generate-return",
    ),
    path(
        "codes/verify-return/",
        VerifyReturnCodeView.as_view(),
        name="codes-verify-return",
    ),
]
