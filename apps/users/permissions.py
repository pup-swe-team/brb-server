"""Permission gates for identity-gated BRB functionality (FR3, FR5)."""

from rest_framework import permissions


class IsIdentityVerified(permissions.BasePermission):
    """
    Require an Admin-approved identity document before allowing an action.

    This is the gate CP-105 puts in front of listing creation and borrow
    requests. It is a server-side check on the caller's own account -- never on
    which dashboard the client happens to have open, per CONTRIBUTING.md 7.2
    rule 2.

    `message` is phrased for an end user rather than a developer, since this
    text reaches the mobile client verbatim in the `detail` field.
    """

    message = (
        "Identity verification is required before you can do this. "
        "Submit an identity document and wait for review to complete."
    )

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            # Let the authentication class produce 401/403 instead.
            return False
        return user.has_verified_identity()
