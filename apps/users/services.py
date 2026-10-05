from django.db import transaction

from .models import User


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
