import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.constants import (
    DEFAULT_EMAIL_VERIFICATION_EXPIRY_DAYS,
    EMAIL_VERIFICATION_EXPIRY_DAYS,
)
from apps.core.selectors import get_int_config
from apps.notifications.constants import NOTIFICATION_TYPE_VERIFICATION_RESULT
from apps.notifications.models import Notification, NotificationType

from .constants import (
    IDENTITY_DOCUMENT_STATUS_APPROVED,
    IDENTITY_DOCUMENT_STATUS_REJECTED,
)
from .models import IdentityDocument, IdentityDocumentStatus, User
from .tokens import EmailVerificationTokenGenerator

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

    The token embeds the user's id, email, current password hash and a
    timestamp, signed with `SECRET_KEY`. That makes it self-expiring and free of
    any storage -- which is why `docs/COPUP_ERD.md` needs no new table for
    CP-102. CP-104's reset link reuses the same mechanism with a shorter lifetime.

    It is not single-use by construction, but that is safe here: `verify_user_email`
    is idempotent, and the token also breaks the moment the user's password or
    last-login changes, so a leaked link cannot be replayed after first use.
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

    Raises whatever `send_mail` raises. Callers decide how loud that is: the
    registration view swallows it so a mail outage cannot leave the caller
    retrying a registration the account already has.
    """
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
