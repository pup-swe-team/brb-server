"""Constants for listings domain (CP-401)."""

# Upload constraints for listing photos (FR7, CP-401)
MAX_LISTING_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_LISTING_PHOTO_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
)

# Status lookup keys
LISTING_STATUS_ACTIVE = "active"
LISTING_STATUS_DEACTIVATED = "deactivated"
LISTING_STATUS_DELETED = "deleted"
