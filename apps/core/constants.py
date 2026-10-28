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

# CP-605 -- number of days after order completion within which a review may be submitted.
REVIEW_WINDOW_DAYS = "review_window_days"
DEFAULT_REVIEW_WINDOW_DAYS = 7
