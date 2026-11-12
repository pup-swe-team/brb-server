"""Constants for the reporting and moderation domain (CP-901, CP-902)."""

REPORT_STATUS_OPEN = "open"
REPORT_STATUS_RESOLVED = "resolved"

REPORT_TARGET_USER = "user"
REPORT_TARGET_LISTING = "listing"
REPORT_TARGET_REVIEW = "review"
REPORT_TARGET_MESSAGE = "message"

ALL_REPORT_TARGETS = (
    REPORT_TARGET_USER,
    REPORT_TARGET_LISTING,
    REPORT_TARGET_REVIEW,
    REPORT_TARGET_MESSAGE,
)

DEFAULT_LISTING_REPORT_CATEGORIES = (
    "prohibited",
    "counterfeit",
    "misleading_description",
    "wrong_category",
    "inappropriate_content",
)

DEFAULT_USER_REPORT_CATEGORIES = (
    "scam_fraud",
    "harassment",
    "fake_account",
    "spam",
    "inappropriate_pfp",
)

DEFAULT_REVIEW_REPORT_CATEGORIES = (
    "fake_review",
    "harassment",
    "spam",
    "offensive_content",
    "irrelevant_review",
)

DEFAULT_MESSAGE_REPORT_CATEGORIES = (
    "scam_fraud",
    "harassment",
    "spam",
    "threats",
    "inappropriate_content",
)
