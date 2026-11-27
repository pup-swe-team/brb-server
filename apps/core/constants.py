"""Keys for `system_configs` rows read at runtime (FR14).

Every value an Admin can tune lives here rather than inline at the call site, so
there is one place to look when someone asks "what is configurable?".

The Admin-facing CRUD for these rows is CP-1104 (Sprint 5). The values are
referenced from Sprint 1, so each reader supplies its own documented default for
when the row is absent -- see `apps.core.selectors`.
"""

# CP-103 -- failed login attempts before the account is locked out.
LOGIN_LOCKOUT_THRESHOLD = "login_lockout_threshold"
DEFAULT_LOGIN_LOCKOUT_THRESHOLD = 5

# CP-103 -- how long the lockout lasts, in minutes.
LOGIN_LOCKOUT_MINUTES = "login_lockout_minutes"
DEFAULT_LOGIN_LOCKOUT_MINUTES = 15

# CP-102 -- days an account may stay unverified before it is removed.
EMAIL_VERIFICATION_EXPIRY_DAYS = "email_verification_expiry_days"
DEFAULT_EMAIL_VERIFICATION_EXPIRY_DAYS = 7

# CP-104 -- minutes a password-reset link stays valid.
PASSWORD_RESET_EXPIRY_MINUTES = "password_reset_expiry_minutes"
DEFAULT_PASSWORD_RESET_EXPIRY_MINUTES = 60


# CP-501 / CP-1104 -- maximum number of items a borrower may hold simultaneously.
BORROWING_LIMIT = "borrowing_limit"
DEFAULT_BORROWING_LIMIT = 3

# CP-1104 -- maximum number of listings a lender may have active concurrently.
LENDING_LIMIT = "lending_limit"
DEFAULT_LENDING_LIMIT = 10

# CP-501 / CP-801 -- how long a borrow request remains valid before expiring (hours).
REQUEST_EXPIRY_HOURS = "request_expiry_hours"
DEFAULT_REQUEST_EXPIRY_HOURS = 24

# CP-504 / CP-505 -- hours a handover or return authentication code stays valid.
AUTH_CODE_EXPIRY_HOURS = "auth_code_expiry_hours"
DEFAULT_AUTH_CODE_EXPIRY_HOURS = 3

# CP-504 / CP-505 -- consecutive failed code entries before verification locks.
AUTH_CODE_LOCKOUT_THRESHOLD = "auth_code_lockout_threshold"
DEFAULT_AUTH_CODE_LOCKOUT_THRESHOLD = 5

# CP-504 / CP-505 -- minutes code verification stays locked after repeated failures.
AUTH_CODE_LOCKOUT_MINUTES = "auth_code_lockout_minutes"
DEFAULT_AUTH_CODE_LOCKOUT_MINUTES = 15

# CP-506 -- days an order may stay Overdue before escalating to Unreturned.
UNRETURNED_ESCALATION_DAYS = "unreturned_escalation_days"
DEFAULT_UNRETURNED_ESCALATION_DAYS = 7

# CP-601 / CP-605 -- number of days after order completion within which a review may be submitted.
REVIEW_WINDOW_DAYS = "review_window_days"
DEFAULT_REVIEW_WINDOW_DAYS = 7

# CP-902 -- number of reports in a rolling window that triggers automatic priority flagging.
AUTO_FLAG_REPORT_THRESHOLD = "auto_flag_report_threshold"
DEFAULT_AUTO_FLAG_REPORT_THRESHOLD = 3

# CP-902 -- rolling window in days for counting repeated reports against a user.
AUTO_FLAG_WINDOW_DAYS = "auto_flag_window_days"
DEFAULT_AUTO_FLAG_WINDOW_DAYS = 30


CONFIG_METADATA: dict[str, dict] = {
    BORROWING_LIMIT: {
        "label": "Borrowing Limit",
        "category": "Borrowing & Lending",
        "description": "Maximum number of items a borrower may hold simultaneously (CP-501).",
        "type": "integer",
        "default": DEFAULT_BORROWING_LIMIT,
        "min": 1,
        "max": 50,
    },
    LENDING_LIMIT: {
        "label": "Lending Limit",
        "category": "Borrowing & Lending",
        "description": "Maximum number of listings a lender may have active concurrently (CP-1104).",
        "type": "integer",
        "default": DEFAULT_LENDING_LIMIT,
        "min": 1,
        "max": 100,
    },
    REQUEST_EXPIRY_HOURS: {
        "label": "Request Expiry (Hours)",
        "category": "Requests & Orders",
        "description": "How long a borrow request remains valid before expiring (CP-501, CP-801).",
        "type": "integer",
        "default": DEFAULT_REQUEST_EXPIRY_HOURS,
        "min": 1,
        "max": 168,
    },
    AUTH_CODE_EXPIRY_HOURS: {
        "label": "Code Expiry (Hours)",
        "category": "Code Verification Rules",
        "description": "Hours a handover or return authentication code stays valid (CP-504, CP-505).",
        "type": "integer",
        "default": DEFAULT_AUTH_CODE_EXPIRY_HOURS,
        "min": 1,
        "max": 48,
    },
    AUTH_CODE_LOCKOUT_THRESHOLD: {
        "label": "Code Lockout Threshold",
        "category": "Code Verification Rules",
        "description": "Consecutive failed code entries before verification locks (CP-504, CP-505).",
        "type": "integer",
        "default": DEFAULT_AUTH_CODE_LOCKOUT_THRESHOLD,
        "min": 1,
        "max": 20,
    },
    AUTH_CODE_LOCKOUT_MINUTES: {
        "label": "Code Lockout Duration (Minutes)",
        "category": "Code Verification Rules",
        "description": "Minutes code verification stays locked after repeated failures (CP-504, CP-505).",
        "type": "integer",
        "default": DEFAULT_AUTH_CODE_LOCKOUT_MINUTES,
        "min": 1,
        "max": 1440,
    },
    REVIEW_WINDOW_DAYS: {
        "label": "Review Window (Days)",
        "category": "Reviews",
        "description": "Days after order completion within which a review may be submitted (CP-601, CP-605).",
        "type": "integer",
        "default": DEFAULT_REVIEW_WINDOW_DAYS,
        "min": 1,
        "max": 90,
    },
    LOGIN_LOCKOUT_THRESHOLD: {
        "label": "Login Lockout Threshold",
        "category": "Security & Accounts",
        "description": "Failed login attempts before the account is locked out (CP-103).",
        "type": "integer",
        "default": DEFAULT_LOGIN_LOCKOUT_THRESHOLD,
        "min": 1,
        "max": 20,
    },
    LOGIN_LOCKOUT_MINUTES: {
        "label": "Login Lockout Duration (Minutes)",
        "category": "Security & Accounts",
        "description": "How long the account lockout lasts in minutes (CP-103).",
        "type": "integer",
        "default": DEFAULT_LOGIN_LOCKOUT_MINUTES,
        "min": 1,
        "max": 1440,
    },
    EMAIL_VERIFICATION_EXPIRY_DAYS: {
        "label": "Email Verification Expiry (Days)",
        "category": "Security & Accounts",
        "description": "Days an account may stay unverified before it is removed (CP-102).",
        "type": "integer",
        "default": DEFAULT_EMAIL_VERIFICATION_EXPIRY_DAYS,
        "min": 1,
        "max": 30,
    },
    PASSWORD_RESET_EXPIRY_MINUTES: {
        "label": "Password Reset Expiry (Minutes)",
        "category": "Security & Accounts",
        "description": "Minutes a password-reset link stays valid (CP-104).",
        "type": "integer",
        "default": DEFAULT_PASSWORD_RESET_EXPIRY_MINUTES,
        "min": 5,
        "max": 1440,
    },
    UNRETURNED_ESCALATION_DAYS: {
        "label": "Unreturned Escalation (Days)",
        "category": "Requests & Orders",
        "description": "Days an order may stay Overdue before escalating to Unreturned (CP-506).",
        "type": "integer",
        "default": DEFAULT_UNRETURNED_ESCALATION_DAYS,
        "min": 1,
        "max": 30,
    },
    AUTO_FLAG_REPORT_THRESHOLD: {
        "label": "Auto-Flag Report Threshold",
        "category": "Reports & Moderation",
        "description": "Number of reports in a rolling window that triggers auto-flagging (CP-902).",
        "type": "integer",
        "default": DEFAULT_AUTO_FLAG_REPORT_THRESHOLD,
        "min": 1,
        "max": 20,
    },
    AUTO_FLAG_WINDOW_DAYS: {
        "label": "Auto-Flag Window (Days)",
        "category": "Reports & Moderation",
        "description": "Rolling window in days for counting repeated reports against a user (CP-902).",
        "type": "integer",
        "default": DEFAULT_AUTO_FLAG_WINDOW_DAYS,
        "min": 1,
        "max": 365,
    },
}
