"""Domain constants and error codes for the chat app (FR10, CP-701, CP-702, CP-703)."""

from apps.orders.constants import (
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_REQUESTED,
    ORDER_STATUS_UNRETURNED,
)

# Order statuses considered "in progress" where blocking is disabled (CP-702).
IN_PROGRESS_ORDER_STATUSES = (
    ORDER_STATUS_REQUESTED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_ACTIVE,
    ORDER_STATUS_OVERDUE,
    ORDER_STATUS_UNRETURNED,
)

# Maximum character length for a single chat message.
MAX_MESSAGE_LENGTH = 2000

# Machine-readable API error codes surfaced via brb_server.exceptions.api_exception_handler.
CODE_SELF_CHAT = "self_chat"
CODE_SELF_BLOCK = "self_block"
CODE_CONVERSATION_BLOCKED = "conversation_blocked"
CODE_USER_BLOCKED = "user_blocked"
CODE_ACTIVE_ORDER_IN_PROGRESS = "active_order_in_progress"
CODE_NOT_BLOCKER = "not_blocker"
CODE_CONVERSATION_RETAINED = "conversation_retained"
CODE_ACCOUNT_INACTIVE = "account_inactive"
CODE_INVALID_CHAT_TARGET = "invalid_chat_target"
