"""Constants, categories, and event mappings for the notifications app (FR11, CP-801, CP-802)."""

NOTIFICATION_TYPE_NEW_REQUEST = "new_request"
NOTIFICATION_TYPE_ACCEPTANCE = "acceptance"
NOTIFICATION_TYPE_DECLINE = "decline"
NOTIFICATION_TYPE_EXPIRY = "expiry"
NOTIFICATION_TYPE_CANCELLATION = "cancellation"
NOTIFICATION_TYPE_CODE_GENERATION = "code_generation"
NOTIFICATION_TYPE_CONFIRMED_HANDOVER = "confirmed_handover"
NOTIFICATION_TYPE_CONFIRMED_RETURN = "confirmed_return"
NOTIFICATION_TYPE_UPCOMING_DUE_DATE = "upcoming_due_date"
NOTIFICATION_TYPE_OVERDUE_STATUS = "overdue_status"
NOTIFICATION_TYPE_UNRETURNED_STATUS = "unreturned_status"
NOTIFICATION_TYPE_NEW_MESSAGE = "new_message"
NOTIFICATION_TYPE_NEW_REVIEW = "new_review"
NOTIFICATION_TYPE_VERIFICATION_RESULT = "verification_result"
NOTIFICATION_TYPE_REPORT_UPDATES = "report_updates"

DEFAULT_NOTIFICATION_TYPES = (
    NOTIFICATION_TYPE_NEW_REQUEST,
    NOTIFICATION_TYPE_ACCEPTANCE,
    NOTIFICATION_TYPE_DECLINE,
    NOTIFICATION_TYPE_EXPIRY,
    NOTIFICATION_TYPE_CANCELLATION,
    NOTIFICATION_TYPE_CODE_GENERATION,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
    NOTIFICATION_TYPE_CONFIRMED_RETURN,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_UNRETURNED_STATUS,
    NOTIFICATION_TYPE_NEW_MESSAGE,
    NOTIFICATION_TYPE_NEW_REVIEW,
    NOTIFICATION_TYPE_VERIFICATION_RESULT,
    NOTIFICATION_TYPE_REPORT_UPDATES,
)

# CP-802: Four grouped email notification preference categories (all on by default).
PREF_CATEGORY_ORDER_UPDATES = "order_updates"
PREF_CATEGORY_MESSAGES = "messages"
PREF_CATEGORY_REVIEWS = "reviews"
PREF_CATEGORY_ACCOUNT_VERIFICATION = "account_verification"

NOTIFICATION_PREFERENCE_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        PREF_CATEGORY_ORDER_UPDATES,
        "Order Updates",
        "Borrow requests, approvals, declines, expirations, cancellations, handover/return codes, due dates, and overdue alerts.",
    ),
    (
        PREF_CATEGORY_MESSAGES,
        "Messages",
        "New one-to-one chat messages from borrowers or lenders.",
    ),
    (
        PREF_CATEGORY_REVIEWS,
        "Reviews",
        "New ratings and reviews received on completed orders.",
    ),
    (
        PREF_CATEGORY_ACCOUNT_VERIFICATION,
        "Account & Verification",
        "Identity verification review decisions and account or report status updates.",
    ),
)

DEFAULT_EMAIL_NOTIFICATION_PREFERENCES: dict[str, bool] = {
    PREF_CATEGORY_ORDER_UPDATES: True,
    PREF_CATEGORY_MESSAGES: True,
    PREF_CATEGORY_REVIEWS: True,
    PREF_CATEGORY_ACCOUNT_VERIFICATION: True,
}

# Accepted input key aliases normalized to the 4 canonical CP-802 category keys.
PREFERENCE_CATEGORY_ALIASES: dict[str, str] = {
    "order_updates": PREF_CATEGORY_ORDER_UPDATES,
    "orderupdates": PREF_CATEGORY_ORDER_UPDATES,
    "order updates": PREF_CATEGORY_ORDER_UPDATES,
    "order_update": PREF_CATEGORY_ORDER_UPDATES,
    "messages": PREF_CATEGORY_MESSAGES,
    "message": PREF_CATEGORY_MESSAGES,
    "reviews": PREF_CATEGORY_REVIEWS,
    "review": PREF_CATEGORY_REVIEWS,
    "account_verification": PREF_CATEGORY_ACCOUNT_VERIFICATION,
    "accountverification": PREF_CATEGORY_ACCOUNT_VERIFICATION,
    "account & verification": PREF_CATEGORY_ACCOUNT_VERIFICATION,
    "account and verification": PREF_CATEGORY_ACCOUNT_VERIFICATION,
    "account_and_verification": PREF_CATEGORY_ACCOUNT_VERIFICATION,
}

# Exhaustive mapping of all 15 FR11 NotificationType events to CP-802's 4 categories.
EVENT_TO_CATEGORY_MAP: dict[str, str] = {
    NOTIFICATION_TYPE_NEW_REQUEST: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_ACCEPTANCE: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_DECLINE: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_EXPIRY: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_CANCELLATION: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_CODE_GENERATION: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_CONFIRMED_RETURN: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_OVERDUE_STATUS: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_UNRETURNED_STATUS: PREF_CATEGORY_ORDER_UPDATES,
    NOTIFICATION_TYPE_NEW_MESSAGE: PREF_CATEGORY_MESSAGES,
    NOTIFICATION_TYPE_NEW_REVIEW: PREF_CATEGORY_REVIEWS,
    NOTIFICATION_TYPE_VERIFICATION_RESULT: PREF_CATEGORY_ACCOUNT_VERIFICATION,
    NOTIFICATION_TYPE_REPORT_UPDATES: PREF_CATEGORY_ACCOUNT_VERIFICATION,
}

# Client-aligned 6-group {push, email} preference keys mapped back to the 4 categories.
CLIENT_CHANNEL_KEYS: tuple[str, ...] = (
    "requests",
    "handover",
    "overdue",
    "messages",
    "reviews",
    "security",
)

CLIENT_CHANNEL_TO_CATEGORY_MAP: dict[str, str] = {
    "requests": PREF_CATEGORY_ORDER_UPDATES,
    "handover": PREF_CATEGORY_ORDER_UPDATES,
    "overdue": PREF_CATEGORY_ORDER_UPDATES,
    "messages": PREF_CATEGORY_MESSAGES,
    "reviews": PREF_CATEGORY_REVIEWS,
    "security": PREF_CATEGORY_ACCOUNT_VERIFICATION,
}

EVENT_TO_CLIENT_CHANNEL_MAP: dict[str, str] = {
    NOTIFICATION_TYPE_NEW_REQUEST: "requests",
    NOTIFICATION_TYPE_ACCEPTANCE: "requests",
    NOTIFICATION_TYPE_DECLINE: "requests",
    NOTIFICATION_TYPE_EXPIRY: "requests",
    NOTIFICATION_TYPE_CANCELLATION: "requests",
    NOTIFICATION_TYPE_CODE_GENERATION: "handover",
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER: "handover",
    NOTIFICATION_TYPE_CONFIRMED_RETURN: "handover",
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE: "overdue",
    NOTIFICATION_TYPE_OVERDUE_STATUS: "overdue",
    NOTIFICATION_TYPE_UNRETURNED_STATUS: "overdue",
    NOTIFICATION_TYPE_NEW_MESSAGE: "messages",
    NOTIFICATION_TYPE_NEW_REVIEW: "reviews",
    NOTIFICATION_TYPE_VERIFICATION_RESULT: "security",
    NOTIFICATION_TYPE_REPORT_UPDATES: "security",
}

NOTIFICATION_METADATA: dict[str, dict[str, str]] = {
    NOTIFICATION_TYPE_NEW_REQUEST: {
        "title": "New Borrow Request",
        "message": "You received a new borrow request.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_ACCEPTANCE: {
        "title": "Borrow Request Accepted",
        "message": "Your borrow request has been accepted by the lender.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_DECLINE: {
        "title": "Borrow Request Declined",
        "message": "Your borrow request was declined.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_EXPIRY: {
        "title": "Borrow Request Expired",
        "message": "A borrow request has expired without a lender response.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CANCELLATION: {
        "title": "Order Cancelled",
        "message": "An order has been cancelled.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CODE_GENERATION: {
        "title": "Handover Code Generated",
        "message": "A verification code has been generated for handover/return.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER: {
        "title": "Handover Confirmed",
        "message": "The item handover has been confirmed. The order is now active.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_CONFIRMED_RETURN: {
        "title": "Return Confirmed",
        "message": "The item return has been confirmed. The order is completed.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE: {
        "title": "Upcoming Due Date",
        "message": "Your borrowed item is due tomorrow. Please prepare for return.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_OVERDUE_STATUS: {
        "title": "Order Overdue",
        "message": "The return deadline for your borrowed item has passed.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_UNRETURNED_STATUS: {
        "title": "Order Marked Unreturned",
        "message": "This order is significantly overdue and has been escalated as unreturned.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_NEW_MESSAGE: {
        "title": "New Message",
        "message": "You received a new message.",
        "reference_type": "conversation",
    },
    NOTIFICATION_TYPE_NEW_REVIEW: {
        "title": "New Review",
        "message": "You received a new review and rating.",
        "reference_type": "order",
    },
    NOTIFICATION_TYPE_VERIFICATION_RESULT: {
        "title": "Identity Verification Update",
        "message": "Your identity verification submission has been reviewed.",
        "reference_type": "verification",
    },
    NOTIFICATION_TYPE_REPORT_UPDATES: {
        "title": "Report / Case Update",
        "message": "There is an update on your reported issue or order escalation.",
        "reference_type": "report",
    },
}

ORDER_PREFIXED_NOTIFICATION_TYPES = (
    NOTIFICATION_TYPE_NEW_REQUEST,
    NOTIFICATION_TYPE_ACCEPTANCE,
    NOTIFICATION_TYPE_DECLINE,
    NOTIFICATION_TYPE_EXPIRY,
    NOTIFICATION_TYPE_CANCELLATION,
    NOTIFICATION_TYPE_CODE_GENERATION,
    NOTIFICATION_TYPE_UPCOMING_DUE_DATE,
    NOTIFICATION_TYPE_OVERDUE_STATUS,
    NOTIFICATION_TYPE_UNRETURNED_STATUS,
    NOTIFICATION_TYPE_CONFIRMED_HANDOVER,
    NOTIFICATION_TYPE_CONFIRMED_RETURN,
)
