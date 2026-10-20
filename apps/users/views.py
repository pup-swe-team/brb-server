import logging

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import log_admin_document_access

from .encryption import decrypt_document_data, detect_document_content_type
from .models import IdentityDocument
from .selectors import get_lender_profile, search_lenders
from .serializers import (
    EmailChangeConfirmSerializer,
    EmailChangeSerializer,
    EmailVerificationSerializer,
    IdentityDocumentOwnerInfoSerializer,
    IdentityDocumentResponseSerializer,
    IdentityDocumentReviewSerializer,
    IdentityDocumentSubmissionSerializer,
    LenderProfileSerializer,
    LenderSearchResultSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileUpdateSerializer,
    RefreshSerializer,
    ResendVerificationSerializer,
    UserRegistrationSerializer,
    UserResponseSerializer,
)
from .services import (
    apply_new_password,
    confirm_email_change,
    deactivate_account,
    deactivation_blockers,
    register_user,
    request_password_reset,
    resend_email_verification,
    review_identity_document,
    send_email_change,
    send_email_verification,
    verify_user_email,
)

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    """
    Endpoint for public user registration with PUP-affiliated email (CP-101).
    POST /api/v1/auth/register/
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = register_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            full_name=serializer.validated_data["full_name"],
            contact_number=serializer.validated_data["contact_number"],
            affiliation=serializer.validated_data["affiliation"],
        )

        # CP-102: the confirmation email is sent after the account row is
        # committed, never inside the registration transaction -- a slow SMTP
        # handshake should not hold a database transaction open. A mail failure
        # is logged and swallowed rather than turned into a 5xx: the account
        # already exists, so failing the request would only push the caller into
        # a retry that fails differently (duplicate email) and teaches them
        # nothing. The safety net is the 7-day cleanup job.
        try:
            send_email_verification(user)
        except Exception:
            logger.exception(
                "CP-102: failed to send verification email to %s", user.email
            )

        response_data = {
            "message": (
                "Registration successful. Check your email to verify your account "
                "before logging in."
            ),
            "user": UserResponseSerializer(user).data,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


class EmailVerificationView(APIView):
    """
    Confirm an email address from a link (CP-102).
    POST /api/v1/auth/verify-email/

    POST rather than GET: the link is followed by a client, and a GET confirmation
    would let any page or prefetcher silently verify an account.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["verified_user"]
        verify_user_email(user)

        return Response(
            {
                "message": "Email address verified. You can now log in.",
                "user": UserResponseSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    """
    Re-send the confirmation link for an unverified account (BE-BUG-0001).
    POST /api/v1/auth/resend-verification/

    Accepts an email address; when it belongs to an account that is still
    unverified and pending review, a fresh link is minted and emailed. Every
    outcome returns the same generic 200 so the endpoint cannot be used as an
    account-existence probe. Throttled to bound outbound mail volume.
    """

    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "resend-verification"

    def post(self, request: Request) -> Response:
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            resend_email_verification(serializer.validated_data["email"])
        except Exception:
            logger.exception("BE-BUG-0001: failed to resend a verification email")

        return Response(
            {
                "message": (
                    "If that email is registered and unverified, we have sent a "
                    "new verification link."
                )
            },
            status=status.HTTP_200_OK,
        )


class LoginView(APIView):
    """
    Exchange credentials for an access/refresh pair (CP-103).
    POST /api/v1/auth/login/
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(
            {
                "user": UserResponseSerializer(serializer.validated_data["user"]).data,
                "tokens": serializer.validated_data["tokens"],
            },
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    """
    The authenticated caller's own account details (BE-BUG-0002, CP-1001).
    GET /api/v1/auth/me/ -- read the profile.
    PATCH /api/v1/auth/me/ -- persist profile field updates.

    Always reports `request.user`'s own row, so a client cannot look at or
    edit anyone else's profile through this endpoint. The PATCH half accepts
    only the profile fields CP-1001 covers; email and password changes live
    behind their own endpoints with their own proofs.
    """

    def get(self, request: Request) -> Response:
        return Response(
            UserResponseSerializer(request.user).data, status=status.HTTP_200_OK
        )

    def patch(self, request: Request) -> Response:
        serializer = ProfileUpdateSerializer(
            instance=request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            UserResponseSerializer(request.user).data, status=status.HTTP_200_OK
        )


class PasswordResetRequestView(APIView):
    """
    Ask for a password-reset link (CP-104).
    POST /api/v1/auth/password-reset/

    Accepts an email address and always answers with the same generic message,
    so the endpoint cannot be used to enumerate registered addresses. Throttled
    to bound outbound mail volume, like resend-verification.
    """

    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "password-reset"

    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_password_reset(serializer.validated_data["email"])
        except Exception:
            logger.exception("CP-104: failed to send a password reset email")

        return Response(
            {
                "message": (
                    "If that email is registered, we have sent a password reset link."
                )
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """
    Honour a reset link and set the new password (CP-104).
    POST /api/v1/auth/password-reset/confirm/

    A dead link -- forged, expired, or already used -- gets one generic
    message. A successful reset re-hashes the password, clears any login
    lockout, and blacklists outstanding sessions.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        apply_new_password(
            serializer.validated_data["reset_user"],
            serializer.validated_data["password"],
        )

        return Response(
            {"message": "Password updated. You can now log in with your new password."},
            status=status.HTTP_200_OK,
        )


class PasswordChangeView(APIView):
    """
    Change the password from inside the app (CP-1001).
    POST /api/v1/auth/password-change/

    Proves the current password first, then re-hashes the new one and
    blacklists every outstanding refresh token -- a session opened with the
    old password cannot outlive it.
    """

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        apply_new_password(
            serializer.validated_data["user"],
            serializer.validated_data["new_password"],
        )

        return Response(
            {"message": "Password changed. All other sessions have been signed out."},
            status=status.HTTP_200_OK,
        )


class EmailChangeView(APIView):
    """
    Request a change of the registered email (CP-1002).
    POST /api/v1/auth/email-change/

    Mails a confirmation link to the *new* address. The account keeps its
    current email until that link is confirmed, so a typo or an address the
    caller does not control can never lock anyone out. Throttled like the
    other mail-sending endpoints.
    """

    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "email-change"

    def post(self, request: Request) -> Response:
        serializer = EmailChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        request.user.pending_email = serializer.validated_data["new_email"]
        request.user.save(update_fields=["pending_email", "updated_at"])

        try:
            send_email_change(request.user)
        except Exception:
            logger.exception("CP-1002: failed to send the email-change link")

        return Response(
            {
                "message": (
                    f"A confirmation link has been sent to "
                    f"{request.user.pending_email}. Your registered email "
                    "changes only once it is confirmed."
                )
            },
            status=status.HTTP_200_OK,
        )


class EmailChangeConfirmView(APIView):
    """
    Confirm a change-of-email link and swap the addresses (CP-1002).
    POST /api/v1/auth/email-change/confirm/

    Anonymous, like verify-email: the mailed link itself is the proof, and the
    recipient is not necessarily signed in on the device that opens it.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = EmailChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["target_user"]
        confirm_email_change(user)

        return Response(
            {
                "message": (
                    "Email address updated. Use the new address the next "
                    "time you log in."
                ),
                "user": UserResponseSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class DeactivateAccountView(APIView):
    """
    Close the caller's own account (CP-1004).
    POST /api/v1/auth/deactivate/

    Refused with a 400 naming the blockers while open orders (borrowed or
    lent) or unresolved unreturned-item cases exist. On success the account is
    marked deactivated, `is_active` goes False so no token can be used or
    refreshed, and outstanding sessions are blacklisted.
    """

    def post(self, request: Request) -> Response:
        blockers = deactivation_blockers(request.user)
        if any(blockers.values()):
            # A plain Response rather than ValidationError: DRF stringifies
            # every value in a ValidationError dict, and the blocker counts
            # should stay JSON numbers the client can render directly.
            return Response(
                {
                    "detail": (
                        "Your account cannot be deactivated while you have "
                        "open orders or unresolved unreturned-item cases. "
                        "Resolve them first."
                    ),
                    "open_orders": blockers["open_orders"],
                    "open_unreturned_cases": blockers["open_unreturned_cases"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        deactivate_account(request.user)

        return Response(
            {
                "message": (
                    "Account deactivated. You can no longer log in; contact "
                    "an administrator if you need it restored."
                )
            },
            status=status.HTTP_200_OK,
        )


class RefreshView(APIView):
    """
    Swap a refresh token for a new access token (CP-103).
    POST /api/v1/auth/token/refresh/
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    End a session by blacklisting its refresh token (CP-103).
    POST /api/v1/auth/logout/

    Requires a valid access token: an anonymous caller gains nothing by
    blacklisting a token, and requiring one keeps "end session" tied to the
    session being ended.
    """

    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


class IdentityDocumentSubmissionView(APIView):
    """
    Store an identity document and its submission record (CP-105).
    POST /api/v1/identity/documents/

    Requires authentication, but *not* an approved document -- submitting one is
    how an account becomes eligible in the first place.

    Multipart parsing is not set here on purpose: the project-wide
    `DEFAULT_PARSER_CLASSES` in settings already includes MultiPartParser, and
    repeating it on one view is how the two lists drift apart.
    """

    def post(self, request: Request) -> Response:
        serializer = IdentityDocumentSubmissionSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        document = serializer.validated_data["created_document"]
        payload = IdentityDocumentResponseSerializer(document).data

        if document.has_profile_mismatch:
            payload["message"] = (
                "Document submitted for review. The name on your document does not "
                "match your registration name, so an administrator will take a "
                "closer look."
            )
        else:
            payload["message"] = "Document submitted for review."

        return Response(payload, status=status.HTTP_201_CREATED)


class IdentityDocumentListView(APIView):
    """
    List the caller's own identity submissions (CP-105).
    GET /api/v1/identity/documents/

    Scoped to `request.user` with no id parameter: the client cannot ask about
    anyone else's documents, and no filter typo can widen it. Returned data
    carries submission status only -- never the stored file (FR3).
    """

    def get(self, request: Request) -> Response:
        documents = (
            IdentityDocument.objects.filter(user=request.user)
            .select_related("document_type", "status")
            .order_by("-submitted_at")
        )

        return Response(
            {
                "count": documents.count(),
                "results": IdentityDocumentResponseSerializer(
                    documents, many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class IdentityDocumentReviewView(APIView):
    """
    Administrator review of a submitted identity verification document (CP-106).
    POST /api/v1/identity/documents/<int:pk>/review/

    Requires administrator authority (request.user.is_staff is True per D-03).
    Approves or rejects the document, persists the decision with reviewer info,
    creates an in-app notification, and dispatches an email notification.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request: Request, pk: int) -> Response:
        document = get_object_or_404(
            IdentityDocument.objects.select_related("user", "status", "document_type"),
            pk=pk,
        )

        serializer = IdentityDocumentReviewSerializer(
            instance=document, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        updated_document = review_identity_document(
            document=document,
            reviewer=request.user,
            action=serializer.validated_data["action"],
            rejection_reason=serializer.validated_data.get("rejection_reason", ""),
            request=request,
        )

        return Response(
            {
                "message": f"Document {updated_document.status.name} successfully.",
                "document": IdentityDocumentResponseSerializer(updated_document).data,
            },
            status=status.HTTP_200_OK,
        )


class IdentityDocumentDownloadView(APIView):
    """
    Secure document download for Administrators only (CP-107, FR3, NFR 4.2).
    GET /api/v1/identity/documents/<int:pk>/download/

    Requires administrator authority (request.user.is_staff is True per D-03).
    Supports both JWTAuthentication and SessionAuthentication so links clicked
    from the Django Admin browser interface work smoothly.
    Decrypts the stored document bytes and logs the access with IP to AdminAccessLog.
    """

    authentication_classes = (
        JWTAuthentication,
        SessionAuthentication,
    )
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request, pk: int) -> HttpResponse | Response:
        document = get_object_or_404(
            IdentityDocument.objects.select_related("user"),
            pk=pk,
        )

        if not document.document_data:
            return Response(
                {"detail": "No document content found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        log_admin_document_access(
            document=document,
            admin=request.user,
            action="download",
            request=request,
        )

        raw_bytes = decrypt_document_data(document.document_data)

        # Infer content type from signature
        content_type, ext = detect_document_content_type(raw_bytes)

        filename = f"identity_doc_{document.id}_{document.id_number}{ext}"
        response = HttpResponse(raw_bytes, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Length"] = len(raw_bytes)
        return response


class IdentityDocumentOwnerInfoView(APIView):
    """
    Release name and contact details of a document owner (CP-107, FR3).
    GET /api/v1/identity/documents/<int:pk>/owner-info/

    Requires administrator authority (request.user.is_staff is True per D-03).
    Returns only the user's full_name, email, contact_number, and affiliation.
    Never includes document_data or id_number.
    Logs the access to AdminAccessLog (action='contact_release').
    """

    authentication_classes = (
        JWTAuthentication,
        SessionAuthentication,
    )
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request: Request, pk: int) -> Response:
        document = get_object_or_404(
            IdentityDocument.objects.select_related("user"),
            pk=pk,
        )

        log_admin_document_access(
            document=document,
            admin=request.user,
            action="contact_release",
            request=request,
        )

        serializer = IdentityDocumentOwnerInfoSerializer(
            document.user, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class LenderSearchView(generics.ListAPIView):
    """
    Search active, verified lenders by name (CP-302).
    GET /api/v1/lenders/?q=<name>

    Excludes suspended/revoked lenders and non-lenders.
    Returns public profile info with active listing count.
    """

    serializer_class = LenderSearchResultSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        q = self.request.query_params.get("q")
        return search_lenders(q=q)


class LenderProfileView(APIView):
    """
    Public profile of a verified lender (CP-304).
    GET /api/v1/lenders/<int:pk>/

    Returns public lender information, average rating, review count,
    and active listings. Returns 404 for non-existent, non-lender,
    suspended, banned, or deactivated users.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        lender = get_lender_profile(user_id=pk)
        if lender is None:
            raise Http404("Lender not found.")

        serializer = LenderProfileSerializer(lender, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
