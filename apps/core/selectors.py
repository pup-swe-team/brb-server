"""Read helpers for platform-wide runtime configuration (FR14).

`SystemConfig` rows are the single source of truth for every "Admin-configurable"
value. The lookup endpoints that let an Admin edit them are CP-1104 (Sprint 5),
but the *values* are referenced from Sprint 1 onwards, so a missing row has to
mean "fall back to the documented default" rather than "raise". See
docs/BRB_BACKEND_SPRINTS.md, "Notes for OpenCode".
"""

from .models import SystemConfig


def get_config(key: str, default: str = "") -> str:
    """Return the raw string value for `key`, or `default` if unset."""
    try:
        return SystemConfig.objects.get(pk=key).config_value
    except SystemConfig.DoesNotExist:
        return default


def get_int_config(key: str, default: int) -> int:
    """
    Return the integer value for `key`, or `default`.

    An Admin can type anything into a text config row, so a value that is not a
    clean integer falls back to `default` instead of crashing the endpoint that
    reads it. A malformed config should degrade to the documented behaviour, not
    take the feature down.
    """
    raw_value = get_config(key, "")
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default
