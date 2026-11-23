"""API views for reporting users, listings, reviews, and messages (CP-901)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import (
    ListingReportCategory,
    MessageReportCategory,
    ReviewReportCategory,
    UserReportCategory,
)
from .serializers import (
    ListingReportCreateSerializer,
    MessageReportCreateSerializer,
    ReportCategoryItemSerializer,
    ReviewReportCreateSerializer,
    UnifiedReportCreateSerializer,
    UserReportCreateSerializer,
    serialize_report,
)
from .services import (
    submit_listing_report,
    submit_message_report,
    submit_report,
    submit_review_report,
    submit_user_report,
)


class ReportCategoriesListView(APIView):
    """
    GET /api/v1/reports/categories/
    Return all report categories grouped by target type (user, listing, review, message).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(
            {
                "user": ReportCategoryItemSerializer(
                    UserReportCategory.objects.order_by("id"), many=True
                ).data,
                "listing": ReportCategoryItemSerializer(
                    ListingReportCategory.objects.order_by("id"), many=True
                ).data,
                "review": ReportCategoryItemSerializer(
                    ReviewReportCategory.objects.order_by("id"), many=True
                ).data,
                "message": ReportCategoryItemSerializer(
                    MessageReportCategory.objects.order_by("id"), many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class UnifiedReportCreateView(APIView):
    """
    POST /api/v1/reports/
    Submit a report for a user, listing, review, or message creating an Open queue entry (CP-901).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = UnifiedReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = submit_report(
            reporter=request.user,
            target_type=serializer.validated_data["target_type"],
            target_id=serializer.validated_data["target_id"],
            category=serializer.validated_data["resolved_category"],
            description=serializer.validated_data["description"],
            order_id=serializer.validated_data.get("resolved_order_id"),
        )
        return Response(serialize_report(report), status=status.HTTP_201_CREATED)


class UserReportCreateView(APIView):
    """
    POST /api/v1/reports/users/
    POST /api/v1/users/<int:pk>/report/
    Submit an open report against a user profile or order counterparty (CP-901).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int | None = None) -> Response:
        serializer = UserReportCreateSerializer(
            data=request.data,
            context={"request": request, "target_id": pk},
        )
        serializer.is_valid(raise_exception=True)
        report = submit_user_report(
            reporter=request.user,
            target_user_id=serializer.validated_data["resolved_target_id"],
            category=serializer.validated_data["resolved_category"],
            description=serializer.validated_data["description"],
            order_id=serializer.validated_data.get("resolved_order_id"),
        )
        return Response(serialize_report(report), status=status.HTTP_201_CREATED)


class ListingReportCreateView(APIView):
    """
    POST /api/v1/reports/listings/
    POST /api/v1/listings/<int:pk>/report/
    Submit an open report against a listing (CP-901).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int | None = None) -> Response:
        serializer = ListingReportCreateSerializer(
            data=request.data,
            context={"request": request, "target_id": pk},
        )
        serializer.is_valid(raise_exception=True)
        report = submit_listing_report(
            reporter=request.user,
            target_listing_id=serializer.validated_data["resolved_target_id"],
            category=serializer.validated_data["resolved_category"],
            description=serializer.validated_data["description"],
        )
        return Response(serialize_report(report), status=status.HTTP_201_CREATED)


class ReviewReportCreateView(APIView):
    """
    POST /api/v1/reports/reviews/
    POST /api/v1/reviews/<int:pk>/report/
    Submit an open report against a review (CP-901, ties to CP-601).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int | None = None) -> Response:
        serializer = ReviewReportCreateSerializer(
            data=request.data,
            context={"request": request, "target_id": pk},
        )
        serializer.is_valid(raise_exception=True)
        report = submit_review_report(
            reporter=request.user,
            target_review_id=serializer.validated_data["resolved_target_id"],
            category=serializer.validated_data["resolved_category"],
            description=serializer.validated_data["description"],
        )
        return Response(serialize_report(report), status=status.HTTP_201_CREATED)


class MessageReportCreateView(APIView):
    """
    POST /api/v1/reports/messages/
    POST /api/v1/messages/<int:pk>/report/
    Submit an open report against a chat message (CP-901).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int | None = None) -> Response:
        serializer = MessageReportCreateSerializer(
            data=request.data,
            context={"request": request, "target_id": pk},
        )
        serializer.is_valid(raise_exception=True)
        report = submit_message_report(
            reporter=request.user,
            target_message_id=serializer.validated_data["resolved_target_id"],
            category=serializer.validated_data["resolved_category"],
            description=serializer.validated_data["description"],
        )
        return Response(serialize_report(report), status=status.HTTP_201_CREATED)
