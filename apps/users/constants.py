import re

# Philippine mobile number regex (e.g., 09171234567 or +639171234567)
PHILIPPINES_MOBILE_REGEX = re.compile(r"^(?:09|\+639)\d{9}$")

# Affiliations permissible for public self-registration
ALLOWED_REGISTRATION_AFFILIATIONS = ("Student", "Faculty", "Staff")

# Lookup-table seeds for identity verification (CP-105). These are real tables
# per DECISIONS.md D-02, but the platform needs the rows to exist before anyone
# can submit a document, so they are seeded by migration.
IDENTITY_DOCUMENT_TYPE_PUP_ID = "pup_id"
IDENTITY_DOCUMENT_TYPE_GOVERNMENT_ID = "government_id"
IDENTITY_DOCUMENT_TYPES = (
    IDENTITY_DOCUMENT_TYPE_PUP_ID,
    IDENTITY_DOCUMENT_TYPE_GOVERNMENT_ID,
)

IDENTITY_DOCUMENT_STATUS_PENDING = "pending"
IDENTITY_DOCUMENT_STATUS_APPROVED = "approved"
IDENTITY_DOCUMENT_STATUS_REJECTED = "rejected"
IDENTITY_DOCUMENT_STATUSES = (
    IDENTITY_DOCUMENT_STATUS_PENDING,
    IDENTITY_DOCUMENT_STATUS_APPROVED,
    IDENTITY_DOCUMENT_STATUS_REJECTED,
)

# CP-105 upload limits. JPEG/PNG/PDF only, 5MB cap, mirroring the image rule
# CP-401 applies to listing photos.
MAX_IDENTITY_DOCUMENT_BYTES = 5 * 1024 * 1024
ALLOWED_IDENTITY_DOCUMENT_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "application/pdf",
)

# Name comparison for the CP-105 mismatch flag: case, punctuation and spacing
# differ freely between a registration form and a printed ID, so compare on
# letters and digits only.
_NAME_NOISE_REGEX = re.compile(r"[^A-Z0-9 ]+")


def normalize_name(value: str) -> str:
    """Reduce a name to uppercase letters/digits in single spaces."""
    upper_cased = value.upper().replace("-", " ").replace(".", " ")
    without_noise = _NAME_NOISE_REGEX.sub(" ", upper_cased)
    return " ".join(without_noise.split())
