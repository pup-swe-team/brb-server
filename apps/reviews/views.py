"""API views for mutual reviews and ratings (CP-601, CP-1102)."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.orders.models import Order
from apps.users.models import User

from .models import Review
from .selectors import (
    get_order_reviews,
    get_user_rating_stats,
    get_user_received_reviews,
)
from .serializers import ReviewCreateSerializer, ReviewResponseSerializer
from .services import admin_remove_review, submit_review


class OrderReviewListCreateView(APIView):
    """
    GET  /api/v1/orders/<int:order_id>/reviews/ — list reviews for an order.
    POST /api/v1/orders/<int:order_id>/reviews/ — submit a review on a completed order (CP-601).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, order_id: int) -> Response:
        order = get_object_or_404(
            Order.objects.select_related("listing", "listing__lender", "borrower"),
            pk=order_id,
        )
        if not request.user.is_staff and request.user.pk not in (
            order.borrower_id,
            order.listing.lender_id,
        ):
            raise PermissionDenied(
                "Only participants of this order may view its reviews."
            )
        reviews = get_order_reviews(order)
        serializer = ReviewResponseSerializer(
            reviews,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request: Request, order_id: int) -> Response:
        serializer = ReviewCreateSerializer(
            data=request.data,
            context={"request": request, "order_id": order_id},
        )
        serializer.is_valid(raise_exception=True)
        review = submit_review(
            order_id=order_id,
            reviewer=request.user,
            rating=serializer.validated_data["rating"],
            comment=serializer.validated_data.get("comment"),
        )
        output = ReviewResponseSerializer(review, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)


class ReviewCreateView(APIView):
    """
    POST /api/v1/reviews/ — submit a review specifying order_id in the request body (CP-601).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = ReviewCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        review = submit_review(
            order_id=serializer.validated_data["resolved_order_id"],
            reviewer=request.user,
            rating=serializer.validated_data["rating"],
            comment=serializer.validated_data.get("comment"),
        )
        output = ReviewResponseSerializer(review, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)


class ReviewDetailView(APIView):
    """
    GET /api/v1/reviews/<int:pk>/ — retrieve a non-deleted review with its report action link.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        review = get_object_or_404(
            Review.objects.select_related(
                "reviewer",
                "order",
                "order__listing",
                "order__listing__lender",
                "order__borrower",
            ),
            pk=pk,
            deleted_at__isnull=True,
        )
        serializer = ReviewResponseSerializer(review, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserReviewListView(APIView):
    """
    GET /api/v1/users/<int:user_id>/reviews/ — list reviews received by a user and their rating stats.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        stats = get_user_rating_stats(user)
        reviews = get_user_received_reviews(user.pk)
        serializer = ReviewResponseSerializer(
            reviews,
            many=True,
            context={"request": request},
        )
        return Response(
            {
                "user_id": user.pk,
                "average_rating": stats["average_rating"],
                "review_count": stats["review_count"],
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminRemoveReviewView(APIView):
    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def delete(self, request, pk: int):
        admin_remove_review(review_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
