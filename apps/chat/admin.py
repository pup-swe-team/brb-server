"""Django Admin registrations for chat models with CP-703 retention safeguards."""

from __future__ import annotations

from django.contrib import admin, messages
from django.http import HttpRequest

from apps.audit.services import log_admin_action

from .models import Conversation, Message, UserBlock
from .selectors import is_conversation_retained


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("id", "sender", "content", "sent_at", "read_at")
    readonly_fields = ("id", "sender", "content", "sent_at", "read_at")
    ordering = ("sent_at", "id")
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "conversation_id",
        "user_a",
        "user_b",
        "listing",
        "order",
        "is_blocked",
        "retained_for_review",
        "updated_at",
    )
    list_filter = ("is_blocked", "created_at", "updated_at")
    search_fields = (
        "user_a__full_name",
        "user_a__email",
        "user_b__full_name",
        "user_b__email",
        "listing__title",
    )
    readonly_fields = (
        "conversation_id",
        "user_a_deleted_at",
        "user_b_deleted_at",
        "created_at",
        "updated_at",
    )
    inlines = (MessageInline,)

    @admin.display(boolean=True, description="Retained (CP-703)")
    def retained_for_review(self, obj: Conversation) -> bool:
        return is_conversation_retained(obj)

    def change_view(
        self, request: HttpRequest, object_id, form_url="", extra_context=None
    ):
        conv = self.get_object(request, object_id)
        if conv is not None and request.user.is_authenticated and request.user.is_staff:
            log_admin_action(
                admin=request.user,
                action="view_conversation",
                target_type="conversation",
                target_id=conv.conversation_id,
                details=f"Viewed conversation #{conv.conversation_id} in Django Admin",
                request=request,
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        if obj is not None and is_conversation_retained(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset) -> None:
        retained_ids = [
            conv.conversation_id for conv in queryset if is_conversation_retained(conv)
        ]
        if retained_ids:
            self.message_user(
                request,
                (
                    "Conversations linked to open reports or disputed orders cannot "
                    f"be deleted (retained IDs: {', '.join(map(str, retained_ids))})."
                ),
                level=messages.ERROR,
            )
            queryset = queryset.exclude(conversation_id__in=retained_ids)
        if queryset.exists():
            super().delete_queryset(request, queryset)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "sent_at", "read_at")
    list_filter = ("sent_at",)
    search_fields = ("content", "sender__full_name", "sender__email")
    readonly_fields = ("sent_at",)

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        if (
            obj is not None
            and obj.conversation_id
            and is_conversation_retained(obj.conversation)
        ):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("id", "blocker", "blocked", "created_at")
    search_fields = (
        "blocker__full_name",
        "blocker__email",
        "blocked__full_name",
        "blocked__email",
    )
    readonly_fields = ("created_at",)
