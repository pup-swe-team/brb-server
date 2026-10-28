from django.urls import path

from .views import (
    ApplyLenderView,
    DeactivateAccountView,
    EmailChangeConfirmView,
    EmailChangeView,
    EmailVerificationView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PasswordResetValidateView,
    RefreshView,
    RegisterView,
    ResendVerificationView,
)
from .dashboards import BorrowerDashboardView, LenderDashboardView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("verify-email/", EmailVerificationView.as_view(), name="auth-verify-email"),
    path(
        "resend-verification/",
        ResendVerificationView.as_view(),
        name="auth-resend-verification",
    ),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("me/", MeView.as_view(), name="auth-me"),
    # CP-1003 -- apply for the Lender role.
    path("apply-lender/", ApplyLenderView.as_view(), name="auth-apply-lender"),
    path("token/refresh/", RefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    # CP-104 -- password recovery.
    path(
        "password-reset/",
        PasswordResetRequestView.as_view(),
        name="auth-password-reset",
    ),
    path(
        "password-reset/validate/",
        PasswordResetValidateView.as_view(),
        name="auth-password-reset-validate",
    ),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    # CP-1001 -- profile edit and password change.
    path(
        "password-change/",
        PasswordChangeView.as_view(),
        name="auth-password-change",
    ),
    # CP-1002 -- change of registered email.
    path(
        "email-change/",
        EmailChangeView.as_view(),
        name="auth-email-change",
    ),
    path(
        "email-change/confirm/",
        EmailChangeConfirmView.as_view(),
        name="auth-email-change-confirm",
    ),
    # CP-1004 -- self-service account closure.
    path(
        "deactivate/",
        DeactivateAccountView.as_view(),
        name="auth-deactivate",
    ),
    # CP-201/203/204 -- dashboards
    path(
        "dashboard/borrower/",
        BorrowerDashboardView.as_view(),
        name="auth-dashboard-borrower",
    ),
    path(
        "dashboard/lender/", LenderDashboardView.as_view(), name="auth-dashboard-lender"
    ),
    path(
        "borrower/dashboard/",
        BorrowerDashboardView.as_view(),
        name="borrower-dashboard",
    ),
    path("lender/dashboard/", LenderDashboardView.as_view(), name="lender-dashboard"),
]
