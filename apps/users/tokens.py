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
`_make_hash_value` is the other departure: it folds in when the confirmation
email was last sent, which the parent has no notion of (F-BUG-0002-001).
"""

from datetime import UTC

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
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

    def _make_hash_value(self, user, timestamp: int) -> str:
        """
        The parent's hash plus the account's last verification send.

        The parent hashes pk/password/last_login/timestamp/email -- none of
        which move when the "resend" button is pressed, so every link minted
        for an unchanged account was byte-identical: a resend mailed a token
        that matched the link already sitting in the inbox, and both kept
        verifying (F-BUG-0002-001). Appending `email_verification_sent_at`
        makes each dispatch mint a new token, silently retiring the previous
        one. A `None` send time appends nothing, so accounts and links minted
        before the column existed keep validating unchanged.

        The timestamp is normalised (UTC, no tzinfo) so the value hashed at
        mint time always matches the value read back from the database, on
        SQLite and Postgres alike.
        """
        base = super()._make_hash_value(user, timestamp)
        sent_at = getattr(user, "email_verification_sent_at", None)
        if sent_at is None:
            stamp = ""
        else:
            if timezone.is_aware(sent_at):
                sent_at = sent_at.astimezone(UTC)
            stamp = sent_at.replace(tzinfo=None).isoformat()
        return f"{base}{stamp}"

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
