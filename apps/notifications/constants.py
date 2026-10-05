"""Constants and lookup-table values for the notifications app (FR11)."""

NOTIFICATION_TYPE_VERIFICATION_RESULT = "verification_result"

DEFAULT_NOTIFICATION_TYPES = (
    "new_request",
    "acceptance",
    "decline",
    "expiry",
    "cancellation",
    "code_generation",
    "confirmed_handover",
    "confirmed_return",
    "upcoming_due_date",
    "overdue_status",
    "unreturned_status",
    "new_message",
    "new_review",
    NOTIFICATION_TYPE_VERIFICATION_RESULT,
    "report_updates",
)
