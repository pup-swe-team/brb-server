from django.urls import path

from .views import (
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
    RefreshView,
    RegisterView,
    ResendVerificationView,
)

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
    path("token/refresh/", RefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    # CP-104 -- password recovery.
    path(
        "password-reset/",
        PasswordResetRequestView.as_view(),
        name="auth-password-reset",
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
]
