import logging

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import IdentityDocument
from .serializers import (
    EmailVerificationSerializer,
    IdentityDocumentResponseSerializer,
    IdentityDocumentReviewSerializer,
    IdentityDocumentSubmissionSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    UserRegistrationSerializer,
    UserResponseSerializer,
)
from .services import (
    register_user,
    review_identity_document,
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
        )

        return Response(
            {
                "message": f"Document {updated_document.status.name} successfully.",
                "document": IdentityDocumentResponseSerializer(updated_document).data,
            },
            status=status.HTTP_200_OK,
        )
