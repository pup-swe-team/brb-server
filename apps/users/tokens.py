"""Token generator for CP-102 email-confirmation links.

Django ships `PasswordResetTokenGenerator` and reuses it for its own password
reset. Its expiry check is hard-coded to the global `PASSWORD_RESET_TIMEOUT`
setting (`django/contrib/auth/tokens.py`), which is the wrong knob here: CP-102
links should live for the account's grace period (7 days by default,
Admin-configurable) and CP-104's reset links need a much shorter window. One
global setting cannot serve both without one ticket silently changing the
other's behaviour, so the expiry is moved onto an instance attribute instead.

`check_token` below is a faithful copy of the parent's, differing only in where
the timeout comes from. It reuses the parent's private helpers rather than
re-deriving the HMAC, so the two cannot drift on salt construction.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Self-expiring confirmation token whose lifetime is set per call."""

    # A distinct salt from the parent, so a verification token can never be
    # replayed against Django's password-reset view or vice versa.
    key_salt = "brb.apps.users.EmailVerificationTokenGenerator"

    def __init__(self, max_age_seconds: int) -> None:
        super().__init__()
        self.max_age_seconds = max_age_seconds

    def check_token(self, user, token) -> bool:
        """Mirrors the parent's checks, but against `self.max_age_seconds`."""
        if not (user and token):
            return False

        try:
            ts_b36, _ = token.split("-")
        except ValueError:
            return False

        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False

        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(
                self._make_token_with_timestamp(user, ts, secret), token
            ):
                break
        else:
            return False

        # The one line that differs from the parent: our own lifetime rather than
        # the global PASSWORD_RESET_TIMEOUT. Positive form so it reads as
        # "inside the window".
        return (self._num_seconds(self._now()) - ts) <= self.max_age_seconds
