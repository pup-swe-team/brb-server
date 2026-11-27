"""DRF API views for 1-to-1 chat, blocking, and Admin retention review (CP-701, CP-702, CP-703)."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import log_admin_action
from apps.orders.models import Dispute
from apps.users.models import User

from .models import Conversation, Message, UserBlock
from .selectors import (
    get_active_blocks_between_users,
    get_conversation_messages,
    get_user_unread_chat_counts,
    list_admin_conversations,
    list_user_conversations,
    pair_conversation_q,
)
from .serializers import (
    AdminConversationDetailSerializer,
    AdminConversationListSerializer,
    ConversationSerializer,
    EntryPointChatSerializer,
    MessageSerializer,
    SendMessageSerializer,
    StartConversationSerializer,
    UserBlockSerializer,
)
from .services import (
    block_user_from_chat,
    delete_conversation_for_user,
    get_participant_conversation,
    mark_conversation_read,
    send_message,
    start_or_get_conversation,
    unblock_user_from_chat,
)


class ConversationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MessagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class ConversationListCreateView(APIView):
    """
    GET  /api/v1/conversations/ — List authenticated user's chat threads + unread counts (CP-701).
    POST /api/v1/conversations/ — Start or reuse a chat from listing_id or order_id (CP-701).
    """

    permission_classes = (IsAuthenticated,)
    pagination_class = ConversationPagination

    def get(self, request: Request) -> Response:
        queryset = list_user_conversations(request.user)
        unread_summary = get_user_unread_chat_counts(request.user)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = ConversationSerializer(
                page, many=True, context={"request": request}
            )
            response = paginator.get_paginated_response(serializer.data)
            response.data["total_unread_count"] = unread_summary["unread_count"]
            response.data["unread_conversations_count"] = unread_summary[
                "unread_conversations_count"
            ]
            return response

        serializer = ConversationSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(
            {
                "count": queryset.count(),
                "total_unread_count": unread_summary["unread_count"],
                "unread_conversations_count": unread_summary[
                    "unread_conversations_count"
                ],
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request) -> Response:
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, created = start_or_get_conversation(
            requester=request.user,
            participant_id=serializer.validated_data.get("participant_id"),
            listing_id=serializer.validated_data.get("listing_id"),
            order_id=serializer.validated_data.get("order_id"),
            initial_message=serializer.validated_data.get("initial_message"),
        )
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StartListingChatView(APIView):
    """
    POST /api/v1/listings/<int:listing_id>/chat/
    Start or retrieve a 1-to-1 chat thread from a listing page (CP-701).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, listing_id: int) -> Response:
        serializer = EntryPointChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, created = start_or_get_conversation(
            requester=request.user,
            listing_id=listing_id,
            initial_message=serializer.validated_data.get("initial_message"),
        )
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class StartOrderChatView(APIView):
    """
    POST /api/v1/orders/<int:order_id>/chat/
    Start or retrieve a 1-to-1 chat thread from an order (CP-701).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, order_id: int) -> Response:
        serializer = EntryPointChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, created = start_or_get_conversation(
            requester=request.user,
            order_id=order_id,
            initial_message=serializer.validated_data.get("initial_message"),
        )
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConversationUnreadCountView(APIView):
    """
    GET /api/v1/conversations/unread-count/
    Lightweight polling endpoint for unread chat message indicators (CP-701).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        counts = get_user_unread_chat_counts(request.user)
        return Response(counts, status=status.HTTP_200_OK)


class ConversationDetailView(APIView):
    """
    GET    /api/v1/conversations/<int:conversation_id>/ — Conversation metadata.
    DELETE /api/v1/conversations/<int:conversation_id>/ — Delete/hide conversation with CP-703 retention override.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        result = delete_conversation_for_user(
            conversation=conversation,
            user=request.user,
        )
        return Response(result, status=status.HTTP_200_OK)


class ConversationMessageListCreateView(APIView):
    """
    GET  /api/v1/conversations/<int:conversation_id>/messages/ — Message history & polling (?after_id=, ?since=, ?mark_read=true).
    POST /api/v1/conversations/<int:conversation_id>/messages/ — Send a new message (enforces CP-702 block).
    """

    permission_classes = (IsAuthenticated,)
    pagination_class = MessagePagination

    def get(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )

        after_id: int | None = None
        raw_after_id = request.query_params.get("after_id")
        if raw_after_id is not None and raw_after_id.strip() != "":
            try:
                after_id = int(raw_after_id.strip())
                if after_id < 0:
                    raise ValueError
            except ValueError as exc:
                raise ValidationError(
                    {"after_id": "after_id must be a non-negative integer."}
                ) from exc

        since = None
        raw_since = request.query_params.get("since")
        if raw_since is not None and raw_since.strip() != "":
            since = parse_datetime(raw_since.strip())
            if since is None:
                raise ValidationError(
                    {"since": "since must be a valid ISO-8601 datetime string."}
                )

        if (request.query_params.get("mark_read") or "").strip().lower() in (
            "true",
            "1",
        ):
            mark_conversation_read(conversation=conversation, reader=request.user)

        queryset = get_conversation_messages(
            conversation,
            after_id=after_id,
            since=since,
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = MessageSerializer(
                page, many=True, context={"request": request}
            )
            return paginator.get_paginated_response(serializer.data)

        serializer = MessageSerializer(
            queryset, many=True, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = send_message(
            conversation=conversation,
            sender=request.user,
            content=serializer.validated_data["content"],
        )
        return Response(
            MessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ConversationMarkReadView(APIView):
    """
    POST /api/v1/conversations/<int:conversation_id>/read/
    Mark all unread counterparty messages in the conversation as read (CP-701).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        marked = mark_conversation_read(
            conversation=conversation,
            reader=request.user,
        )
        counts = get_user_unread_chat_counts(request.user)
        return Response(
            {
                "conversation_id": conversation.conversation_id,
                "marked_read": marked,
                "unread_count": 0,
                "total_unread_count": counts["unread_count"],
            },
            status=status.HTTP_200_OK,
        )


class ConversationBlockView(APIView):
    """
    POST /api/v1/conversations/<int:conversation_id>/block/
    Block the counterparty in chat; disabled (409) while an order is in progress (CP-702).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        other_user = conversation.other_participant(request.user)
        block_user_from_chat(blocker=request.user, target_user=other_user)
        conversation.refresh_from_db()
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class ConversationUnblockView(APIView):
    """
    POST /api/v1/conversations/<int:conversation_id>/unblock/
    Unblock a previously blocked counterparty (blocker-only, CP-702).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, conversation_id: int) -> Response:
        conversation = get_participant_conversation(
            conversation_id=conversation_id,
            user=request.user,
        )
        other_user = conversation.other_participant(request.user)
        unblock_user_from_chat(requester=request.user, target_user=other_user)
        conversation.refresh_from_db()
        return Response(
            ConversationSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class UserBlockListView(APIView):
    """
    GET /api/v1/chat/blocks/
    List users currently blocked in chat by the authenticated user (CP-702).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        blocks = (
            UserBlock.objects.filter(blocker=request.user)
            .select_related("blocked")
            .order_by("-created_at", "-id")
        )
        return Response(
            UserBlockSerializer(blocks, many=True, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class UserBlockActionView(APIView):
    """
    GET    /api/v1/users/<int:user_id>/block/ — Inspect block status between requester and user (CP-702).
    POST   /api/v1/users/<int:user_id>/block/ — Block another user in chat (CP-702).
    DELETE /api/v1/users/<int:user_id>/block/ — Unblock another user in chat (CP-702).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, user_id: int) -> Response:
        target_user = get_object_or_404(User, pk=user_id)
        if target_user.pk == request.user.pk:
            return Response(
                {
                    "is_blocked": False,
                    "blocked_by_me": False,
                    "is_blocked_by_me": False,
                    "blocked_by_id": None,
                },
                status=status.HTTP_200_OK,
            )

        blocks = list(get_active_blocks_between_users(request.user.pk, target_user.pk))
        blocked_convs = Conversation.objects.filter(
            pair_conversation_q(request.user.pk, target_user.pk),
            is_blocked=True,
        )
        is_blocked = bool(blocks) or blocked_convs.exists()
        blocked_by_id = None
        blocked_by_me = False

        if any(b.blocker_id == request.user.pk for b in blocks):
            blocked_by_me = True
            blocked_by_id = request.user.pk
        elif blocks:
            blocked_by_id = blocks[0].blocker_id
        else:
            conv_with_blocker = blocked_convs.exclude(blocked_by__isnull=True).first()
            if conv_with_blocker is not None:
                blocked_by_id = conv_with_blocker.blocked_by_id
                blocked_by_me = blocked_by_id == request.user.pk

        return Response(
            {
                "is_blocked": is_blocked,
                "blocked_by_me": blocked_by_me,
                "is_blocked_by_me": blocked_by_me,
                "blocked_by_id": blocked_by_id,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request, user_id: int) -> Response:
        target_user = get_object_or_404(User, pk=user_id)
        block = block_user_from_chat(blocker=request.user, target_user=target_user)
        return Response(
            UserBlockSerializer(block, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request: Request, user_id: int) -> Response:
        target_user = get_object_or_404(User, pk=user_id)
        unblock_user_from_chat(requester=request.user, target_user=target_user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserUnblockActionView(APIView):
    """
    POST /api/v1/users/<int:user_id>/unblock/
    Client-compatible POST route to remove a block initiated by the requester (CP-702).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, user_id: int) -> Response:
        target_user = get_object_or_404(User, pk=user_id)
        unblock_user_from_chat(requester=request.user, target_user=target_user)
        remaining_blocks = get_active_blocks_between_users(
            request.user.pk, target_user.pk
        ).exists()
        return Response(
            {
                "is_blocked": remaining_blocks,
                "blocked_by_me": False,
                "is_blocked_by_me": False,
            },
            status=status.HTTP_200_OK,
        )


class DisputeConversationView(APIView):
    """
    GET /api/v1/disputes/<int:pk>/conversation/
    Staff/admin-only retained conversation timeline for AdminCaseScreen (CP-703).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request, pk: int) -> Response:
        dispute = get_object_or_404(
            Dispute.objects.select_related(
                "order",
                "order__listing",
                "order__listing__lender",
                "order__borrower",
            ),
            pk=pk,
        )
        order = dispute.order
        borrower_id = order.borrower_id
        lender_id = order.listing.lender_id

        conv_ids = list(
            Conversation.objects.filter(
                Q(order=order)
                | (
                    Q(listing=order.listing)
                    & pair_conversation_q(borrower_id, lender_id)
                )
            ).values_list("conversation_id", flat=True)
        )

        messages_qs = (
            Message.objects.filter(conversation_id__in=conv_ids)
            .select_related("sender")
            .order_by("sent_at", "id")
        )

        log_admin_action(
            admin=request.user,
            action="view_conversation",
            target_type="dispute",
            target_id=dispute.pk,
            details=(
                f"Viewed retained conversation messages for Dispute #{dispute.pk} "
                f"(Order #{order.pk})"
            ),
            request=request,
        )

        payload = [
            {
                "id": str(msg.pk),
                "sender": "lender" if msg.sender_id == lender_id else "borrower",
                "text": msg.content,
                "sentAt": msg.sent_at.isoformat(),
            }
            for msg in messages_qs
        ]
        return Response(payload, status=status.HTTP_200_OK)


class AdminConversationListView(APIView):
    """
    GET /api/v1/admin/conversations/
    Admin review list of conversations (including retained, blocked, and user-deleted threads; CP-703).
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        retained_param = request.query_params.get("retained")
        retained: bool | None = None
        if retained_param is not None and retained_param.strip() != "":
            val = retained_param.strip().lower()
            if val in ("true", "1"):
                retained = True
            elif val in ("false", "0"):
                retained = False

        is_blocked_param = request.query_params.get("is_blocked")
        is_blocked: bool | None = None
        if is_blocked_param is not None and is_blocked_param.strip() != "":
            val = is_blocked_param.strip().lower()
            if val in ("true", "1"):
                is_blocked = True
            elif val in ("false", "0"):
                is_blocked = False

        def _parse_int(param_name: str) -> int | None:
            raw = request.query_params.get(param_name)
            if raw is None or raw.strip() == "":
                return None
            if not raw.strip().isdigit():
                raise ValidationError({param_name: f"{param_name} must be an integer."})
            return int(raw.strip())

        conversations = list_admin_conversations(
            retained=retained,
            order_id=_parse_int("order_id"),
            listing_id=_parse_int("listing_id"),
            user_id=_parse_int("user_id"),
            is_blocked=is_blocked,
        )
        return Response(
            AdminConversationListSerializer(
                conversations, many=True, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )


class AdminConversationDetailView(APIView):
    """
    GET /api/v1/admin/conversations/<int:conversation_id>/
    Admin read-only evidence viewer for a conversation and all its messages (CP-703).
    Logs an immutable AdminAccessLog entry per FR14.
    """

    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def get(self, request: Request, conversation_id: int) -> Response:
        conversation = get_object_or_404(
            Conversation.objects.select_related(
                "user_a",
                "user_b",
                "listing",
                "order",
                "order__status",
                "blocked_by",
            ),
            conversation_id=conversation_id,
        )
        log_admin_action(
            admin=request.user,
            action="view_conversation",
            target_type="conversation",
            target_id=conversation.conversation_id,
            details=(
                f"Viewed conversation #{conversation.conversation_id} "
                f"({conversation.user_a.full_name} & {conversation.user_b.full_name})"
            ),
            request=request,
        )
        return Response(
            AdminConversationDetailSerializer(
                conversation, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )
