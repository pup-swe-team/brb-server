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
