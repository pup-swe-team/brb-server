"""Views for in-app notifications and preferences (FR11, CP-801, CP-802)."""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationPreferencesSerializer, NotificationSerializer
from .services import (
    get_user_notification_preferences,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    update_user_notification_preferences,
)


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListView(APIView):
    """
    List user notifications with unread counts and read/unread filtering (CP-801).
    """

    permission_classes = (IsAuthenticated,)
    pagination_class = NotificationPagination

    def get(self, request: Request) -> Response:
        queryset = (
            Notification.objects.filter(user=request.user)
            .select_related("type")
            .order_by("-created_at", "-id")
        )

        is_read_param = request.query_params.get("is_read")
        if is_read_param is not None:
            val = is_read_param.strip().lower()
            if val in ("true", "1"):
                queryset = queryset.filter(is_read=True)
            elif val in ("false", "0"):
                queryset = queryset.filter(is_read=False)

        unread_count = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response.data["unread_count"] = unread_count
            return response

        serializer = NotificationSerializer(queryset, many=True)
        return Response(
            {
                "count": queryset.count(),
                "unread_count": unread_count,
                "results": serializer.data,
            }
        )


class NotificationMarkReadView(APIView):
    """
    Mark a specific notification as read (CP-801).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, notification_id: int) -> Response:
        try:
            notif = mark_notification_as_read(
                notification_id=notification_id,
                user=request.user,
            )
        except ObjectDoesNotExist:
            return Response(
                {"detail": "Notification not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        unread_count = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        serializer = NotificationSerializer(notif)
        return Response(
            {
                "notification": serializer.data,
                "unread_count": unread_count,
            },
            status=status.HTTP_200_OK,
        )


class NotificationMarkAllReadView(APIView):
    """
    Mark all unread notifications for the authenticated user as read (CP-801).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        updated_count = mark_all_notifications_as_read(user=request.user)
        return Response(
            {
                "marked_read": updated_count,
                "unread_count": 0,
            },
            status=status.HTTP_200_OK,
        )


class NotificationUnreadCountView(APIView):
    """
    Lightweight endpoint to fetch unread notification badge count (CP-801).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({"unread_count": count}, status=status.HTTP_200_OK)


class NotificationPreferencesView(APIView):
    """
    Get or update user notification preferences across channels (CP-801, CP-802).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        prefs = get_user_notification_preferences(request.user)
        return Response(prefs, status=status.HTTP_200_OK)

    def put(self, request: Request) -> Response:
        serializer = NotificationPreferencesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = update_user_notification_preferences(
            user=request.user,
            new_prefs=serializer.validated_data,
        )
        return Response(updated, status=status.HTTP_200_OK)
