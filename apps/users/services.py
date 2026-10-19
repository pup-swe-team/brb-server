import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.constants import (
    DEFAULT_EMAIL_VERIFICATION_EXPIRY_DAYS,
    DEFAULT_PASSWORD_RESET_EXPIRY_MINUTES,
    EMAIL_VERIFICATION_EXPIRY_DAYS,
    PASSWORD_RESET_EXPIRY_MINUTES,
)
from apps.core.selectors import get_int_config
from apps.notifications.constants import NOTIFICATION_TYPE_VERIFICATION_RESULT
from apps.notifications.models import Notification, NotificationType
from apps.orders.models import Order, UnreturnedCase

from .constants import (
    IDENTITY_DOCUMENT_STATUS_APPROVED,
    IDENTITY_DOCUMENT_STATUS_REJECTED,
)
from .models import IdentityDocument, IdentityDocumentStatus, User
from .tokens import (
    EmailChangeTokenGenerator,
    EmailVerificationTokenGenerator,
    PasswordResetTokenGenerator,
)

logger = logging.getLogger(__name__)


def register_user(
    *,
    email: str,
    password: str,
    full_name: str,
    contact_number: str,
    affiliation: str,
) -> User:
    """
    Creates a new user account in a pending/unverified state (CP-101).
    Sets account_status to PENDING_REVIEW and leaves email_verified_at as None.
    Hashed password is saved securely via set_password.
    """
    with transaction.atomic():
        user = User(
            email=email,
            full_name=full_name,
            contact_number=contact_number,
            affiliation=affiliation,
            account_status=User.AccountStatusChoices.PENDING_REVIEW,
            email_verified_at=None,
        )
        user.set_password(password)
        user.save()
        return user


def email_verification_expiry_days() -> int:
    """Days an account may stay unverified, Admin-configurable (CP-102)."""
    return get_int_config(
        EMAIL_VERIFICATION_EXPIRY_DAYS, DEFAULT_EMAIL_VERIFICATION_EXPIRY_DAYS
    )


def email_verification_token_generator() -> EmailVerificationTokenGenerator:
    """
    Token generator whose lifetime matches the account's grace period.

    Tying the two together means a link can never outlive the account it
    verifies, and raising the `email_verification_expiry_days` config extends
    both without a second setting to remember.
    """
    return EmailVerificationTokenGenerator(
        max_age_seconds=email_verification_expiry_days() * 24 * 60 * 60
    )


def build_email_verification_token(user: User) -> str:
    """
    Mint a stateless verification token for `user` (CP-102).

    The token embeds the user's id, email, current password hash, the time the
    latest confirmation email was sent and a timestamp, signed with
    `SECRET_KEY`. That makes it self-expiring and free of any storage -- which
    is why `docs/COPUP_ERD.md` needs no new table for CP-102. CP-104's reset
    link reuses the same mechanism with a shorter lifetime.

    It is not single-use by construction, but that is safe here:
    `verify_user_email` is idempotent. What a resend does change is the send
    time folded into the hash, so each dispatch mails a different token and
    the link already in the inbox stops verifying (F-BUG-0002-001). The token
    still breaks the moment the user's password or last-login changes, so a
    leaked link cannot outlive those either.
    """
    return email_verification_token_generator().make_token(user)


def build_email_verification_url(user: User) -> str:
    """Confirmation link handed to the user in the email body."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = build_email_verification_token(user)
    return f"{settings.EMAIL_VERIFICATION_REDIRECT_URL}?uid={uid}&token={token}"


def send_email_verification(user: User) -> None:
    """
    Email the confirmation link for a freshly registered account (CP-102).

    The send time is stamped onto `user` before the link is minted (the token
    hashes it), and saved only once `send_mail` accepts the message: a resend
    therefore retires the link already in the inbox, while a mail outage
    retires nothing -- nothing is persisted, so the previously mailed link
    keeps working until a resend actually lands (F-BUG-0002-001).

    Raises whatever `send_mail` raises. Callers decide how loud that is: the
    registration view swallows it so a mail outage cannot leave the caller
    retrying a registration the account already has.
    """
    user.email_verification_sent_at = timezone.now()
    verification_url = build_email_verification_url(user)

    send_mail(
        subject="Verify your BRB email address",
        message=(
            f"Hi {user.full_name},\n\n"
            "Confirm your email address to activate your BRB account:\n\n"
            f"{verification_url}\n\n"
            "If you did not create a BRB account, you can ignore this message. "
            "The account is removed automatically if it is not confirmed in time.\n"
        ),
        from_email=None,  # falls back to settings.DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )
    user.save(update_fields=["email_verification_sent_at", "updated_at"])


def verify_user_email(user: User) -> None:
    """
    Flip an account from unverified to fully active (CP-102).

    `account_status` moves PENDING_REVIEW -> ACTIVE, which is the server-side
    half of "grant full access"; the client half is refusing to hand out tokens
    until `email_verified_at` is set (see `LoginSerializer`). Both halves read
    the same field, so neither can drift from the other.
    """
    if user.email_verified_at is not None:
        return

    with transaction.atomic():
        user.email_verified_at = timezone.now()
        if user.account_status == User.AccountStatusChoices.PENDING_REVIEW:
            user.account_status = User.AccountStatusChoices.ACTIVE
        user.save(update_fields=["email_verified_at", "account_status", "updated_at"])


def resend_email_verification(email: str) -> None:
    """
    Re-dispatch the CP-102 confirmation link to an account that still needs it.

    Exists so a user who never received (or lost) the first email can ask for a
    fresh one without re-registering (BE-BUG-0001). It is deliberately
    non-committal: an unknown address, an already-verified account, or a
    non-pending account all silently do nothing, and the caller always returns
    the same generic message -- otherwise this public endpoint becomes a probe
    for which addresses are registered (and which have confirmed).
    """
    user = User.objects.filter(email__iexact=email.strip()).first()
    if user is None:
        return
    if user.email_verified_at is not None:
        return
    if user.account_status != User.AccountStatusChoices.PENDING_REVIEW:
        return
    send_email_verification(user)


# ---------------------------------------------------------------------------
# CP-104 -- password reset
# ---------------------------------------------------------------------------


def password_reset_expiry_minutes() -> int:
    """Minutes a reset link stays valid, Admin-configurable (CP-104)."""
    return get_int_config(
        PASSWORD_RESET_EXPIRY_MINUTES, DEFAULT_PASSWORD_RESET_EXPIRY_MINUTES
    )


def password_reset_token_generator() -> PasswordResetTokenGenerator:
    """Generator whose lifetime matches the CP-104 expiry window."""
    return PasswordResetTokenGenerator(
        max_age_seconds=password_reset_expiry_minutes() * 60
    )


def build_password_reset_url(user: User) -> str:
    """Confirmation link handed to the user in the reset email."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token_generator().make_token(user)
    return f"{settings.PASSWORD_RESET_REDIRECT_URL}?uid={uid}&token={token}"


def send_password_reset(user: User) -> None:
    """
    Email a reset link to the account (CP-104).

    Same dispatch discipline as `send_email_verification`: the send time is
    stamped before the token is minted (the token hashes it) and saved only
    once `send_mail` accepts the message, so a fresh request retires the link
    already in the inbox while a mail outage retires nothing.

    Single-use needs no column: the token hash covers the password hash, so
    the `set_password` in the confirm step kills the token that got there.
    Raises whatever `send_mail` raises; the view logs and swallows it.
    """
    user.password_reset_sent_at = timezone.now()
    reset_url = build_password_reset_url(user)

    send_mail(
        subject="Reset your BRB password",
        message=(
            f"Hi {user.full_name},\n\n"
            "Use the link below to choose a new password. It can only be used "
            f"once and expires in {password_reset_expiry_minutes()} minute(s):\n\n"
            f"{reset_url}\n\n"
            "If you did not request this, you can ignore this message -- "
            "your password has not changed.\n"
        ),
        from_email=None,  # falls back to settings.DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )
    user.save(update_fields=["password_reset_sent_at", "updated_at"])


def request_password_reset(email: str) -> None:
    """
    Dispatch a reset link for `email`, if such an account exists (CP-104).

    Deliberately non-committal, like `resend_email_verification`: an unknown
    address silently does nothing and the caller always returns the same
    generic message, so this public endpoint cannot be used to probe which
    addresses are registered. Every existing account is served -- a suspended
    or deactivated account can change its password but still cannot log in,
    which is enforced at login time.
    """
    user = User.objects.filter(email__iexact=email.strip()).first()
    if user is None:
        return
    send_password_reset(user)


def apply_new_password(user: User, password: str) -> None:
    """
    Set a new password and retire everything the old one protected (CP-104,
    CP-1001).

    Re-hashes through `set_password`, clears any CP-103 lockout (proving inbox
    or current-password access is a stronger signal than the streak), and
    blacklists every outstanding refresh token so sessions opened with the old
    password cannot outlive it. The password change also invalidates any
    unspent password-reset token, because the token hash covers the password
    hash.
    """
    with transaction.atomic():
        user.set_password(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(
            update_fields=[
                "password",
                "failed_login_attempts",
                "locked_until",
                "updated_at",
            ]
        )
    blacklist_outstanding_tokens(user)


def blacklist_outstanding_tokens(user: User) -> None:
    """
    Invalidate every refresh token SimpleJWT still has on file for `user`.

    Used by CP-1001's password change and CP-1004's deactivation: a refresh
    token is the session, so leaving one outstanding would let a caller keep
    minting access tokens after the password changed or the account closed.
    Each token is blacklisted individually because the blacklist table is
    one-row-per-token by design.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


# ---------------------------------------------------------------------------
# CP-1002 -- change of registered email
# ---------------------------------------------------------------------------


def email_change_token_generator() -> EmailChangeTokenGenerator:
    """
    Generator for change-of-email confirmations.

    The window follows the CP-102 grace period rather than CP-104's: both
    confirm that the person controls an address, whereas a reset link grants
    the power to change credentials and earns the shorter leash.
    """
    return EmailChangeTokenGenerator(
        max_age_seconds=email_verification_expiry_days() * 24 * 60 * 60
    )


def build_email_change_url(user: User) -> str:
    """Confirmation link mailed to the new address."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_change_token_generator().make_token(user)
    return f"{settings.EMAIL_CHANGE_REDIRECT_URL}?uid={uid}&token={token}"


def send_email_change(user: User) -> None:
    """
    Email the confirmation link to `user.pending_email` (CP-1002).

    Dispatch discipline matches `send_email_verification`: stamp first, send,
    persist only on success, so each dispatch supersedes the previous link and
    a mail outage changes nothing. `pending_email` must be set by the caller
    before this runs.
    """
    user.email_change_sent_at = timezone.now()
    change_url = build_email_change_url(user)

    send_mail(
        subject="Confirm your new BRB email address",
        message=(
            f"Hi {user.full_name},\n\n"
            "Confirm this new email address for your BRB account:\n\n"
            f"{change_url}\n\n"
            f"Until you confirm, {user.email} stays your account's email "
            "address. If you did not request this, you can ignore this "
            "message.\n"
        ),
        from_email=None,  # falls back to settings.DEFAULT_FROM_EMAIL
        recipient_list=[user.pending_email],
        fail_silently=False,
    )
    user.save(update_fields=["email_change_sent_at", "updated_at"])


def confirm_email_change(user: User) -> None:
    """
    Promote `pending_email` to `email` (CP-1002).

    The serializer re-checks that the address is still free immediately before
    this runs. The old address stops being the account of record here;
    `email_verified_at` is untouched, because confirming the mailed link *is*
    the proof for the new address. Any CP-102 token minted for the old address
    dies with the swap: the parent hash covers the email.
    """
    user.email = user.pending_email
    user.pending_email = None
    user.email_change_sent_at = None
    user.save(
        update_fields=["email", "pending_email", "email_change_sent_at", "updated_at"]
    )


# ---------------------------------------------------------------------------
# CP-1004 -- account deactivation
# ---------------------------------------------------------------------------

# Order statuses that mean a borrow is still in flight. "Requested" counts:
# the item is spoken for, and letting the Borrower vanish leaves the Lender
# holding a request they cannot answer. Terminal states (completed, declined,
# expired, cancelled) do not block.
DEACTIVATION_BLOCKING_ORDER_STATUSES = (
    "requested",
    "confirmed",
    "active",
    "returned",
    "overdue",
    "unreturned",
    "disputed",
)

# Unreturned-case statuses that still need the account around to resolve.
DEACTIVATION_BLOCKING_CASE_STATUSES = ("open", "escalated")


def deactivation_blockers(user: User) -> dict[str, int]:
    """
    Count what must be settled before the account may close (CP-1004).

    Both roles are checked: orders the user borrowed, and orders placed
    against the user's own listings -- a Lender with an active handover cannot
    deactivate either. Unreturned cases are counted separately because the
    checklist names them alongside open orders, and they outlive the order
    statuses that would otherwise look closed.
    """
    borrowed_or_lent = Q(borrower=user) | Q(listing__lender=user)
    open_orders = (
        Order.objects.filter(
            borrowed_or_lent,
            status__name__in=DEACTIVATION_BLOCKING_ORDER_STATUSES,
        )
        .distinct()
        .count()
    )
    open_cases = (
        UnreturnedCase.objects.filter(
            Q(order__borrower=user) | Q(order__listing__lender=user),
            status__name__in=DEACTIVATION_BLOCKING_CASE_STATUSES,
        )
        .distinct()
        .count()
    )
    return {"open_orders": open_orders, "open_unreturned_cases": open_cases}


def deactivate_account(user: User) -> None:
    """
    Close the account (CP-1004).

    `is_active = False` is what actually revokes access: SimpleJWT's
    `USER_AUTHENTICATION_RULE` refuses tokens for inactive users, and
    `LoginSerializer` reports the refusal as `inactive`. `account_status`
    records the reason for the UI and the Admin. Outstanding refresh tokens
    are blacklisted so live sessions die with the account. Listings are left
    alone: CP-205 owns the lender-revocation cascade, and CP-301's search
    filters exclude listings whose lender is no longer active, so a
    deactivated account's listings drop out of search without being deleted.
    """
    with transaction.atomic():
        user.account_status = User.AccountStatusChoices.DEACTIVATED
        user.is_active = False
        user.save(update_fields=["account_status", "is_active", "updated_at"])
    blacklist_outstanding_tokens(user)


def deactivate_unverified_users(*, now=None) -> list[int]:
    """
    Remove accounts that never confirmed their email within the expiry window.

    CP-102 asks for two things that pull against each other: auto-deactivate
    after 7 days, *and* require re-registration with no reactivation path. A row
    left behind holding the email would make re-registration impossible -- the
    address is unique and CP-101 rejects duplicates -- so the "deactivation" is a
    delete. The address returns to the pool and the person starts over, which is
    the only reading under which both halves of the ticket can be true at once.

    Deleting the row is also what actually revokes access. SimpleJWT resolves
    every request back to a user row and rejects the token when it is gone
    (`JWTAuthentication.get_user`), and `TokenRefreshView` fails the same way --
    which is why `RefreshSerializer` below catches the missing user instead of
    letting it surface as a 500.

    Returns the ids of the accounts removed.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=email_verification_expiry_days())

    expired_ids = list(
        User.objects.filter(
            email_verified_at__isnull=True,
            account_status=User.AccountStatusChoices.PENDING_REVIEW,
            created_at__lte=cutoff,
        ).values_list("pk", flat=True)
    )

    if not expired_ids:
        return []

    with transaction.atomic():
        User.objects.filter(pk__in=expired_ids).delete()

    logger.info(
        "CP-102: removed %d unverified account(s): %s", len(expired_ids), expired_ids
    )
    return expired_ids


def send_identity_review_email(document: IdentityDocument) -> None:
    """Send approval or rejection notification email for identity review (CP-106)."""
    user = document.user
    if document.status.name == IDENTITY_DOCUMENT_STATUS_APPROVED:
        subject = "BRB Identity Verification Approved"
        message = (
            f"Hi {user.full_name},\n\n"
            "Your identity verification document has been approved by an administrator. "
            "You now have full access to list items and request borrows on the BRB platform.\n\n"
            "Thank you,\n"
            "BRB Team\n"
        )
    else:
        subject = "BRB Identity Verification Update - Action Required"
        message = (
            f"Hi {user.full_name},\n\n"
            "Your identity verification document was reviewed and could not be approved "
            f"for the following reason:\n\n{document.rejection_reason}\n\n"
            "You may submit a new document for review at any time through your account settings.\n\n"
            "Thank you,\n"
            "BRB Team\n"
        )

    send_mail(
        subject=subject,
        message=message,
        from_email=None,  # falls back to settings.DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )


def review_identity_document(
    *,
    document: IdentityDocument,
    reviewer: User,
    action: str,
    rejection_reason: str = "",
    request: object = None,
) -> IdentityDocument:
    """
    Approve or reject a submitted identity document (CP-106).

    Persists the decision with reviewer audit information (reviewed_by, reviewed_at),
    records an in-app Notification (FR11), creates an audit log entry (CP-107, FR14),
    and dispatches an email notification.
    """
    if action == "approve":
        status_row = IdentityDocumentStatus.objects.get(
            name=IDENTITY_DOCUMENT_STATUS_APPROVED
        )
        reason = ""
    elif action == "reject":
        status_row = IdentityDocumentStatus.objects.get(
            name=IDENTITY_DOCUMENT_STATUS_REJECTED
        )
        reason = rejection_reason.strip()
    else:
        raise ValueError(f"Unknown identity review action: {action}")

    with transaction.atomic():
        document.status = status_row
        document.rejection_reason = reason
        document.reviewed_by = reviewer
        document.reviewed_at = timezone.now()
        document.save(
            update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"]
        )

        notification_type, _ = NotificationType.objects.get_or_create(
            name=NOTIFICATION_TYPE_VERIFICATION_RESULT
        )
        Notification.objects.create(
            user=document.user,
            type=notification_type,
            reference_id=str(document.id),
        )

        from apps.audit.services import log_admin_document_access

        log_admin_document_access(
            document=document,
            admin=reviewer,
            action="review",
            request=request,
        )

    try:
        send_identity_review_email(document)
    except Exception:
        logger.exception(
            "CP-106: failed to send identity review notification email to %s",
            document.user.email,
        )

    return document
