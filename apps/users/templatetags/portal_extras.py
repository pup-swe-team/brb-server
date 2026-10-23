from django import template

from ..portal import document_type_label
from ..portal import initials as _initials

register = template.Library()


@register.filter
def initials(value: str) -> str:
    """Avatar initials, e.g. `Danielo Kim R. Ang|initials` -> `DA`."""
    return _initials(value or "")


@register.filter
def doc_type_label(value: str) -> str:
    """Human label for a document type lookup row, e.g. `pup_id` -> `PUP ID`."""
    return document_type_label(value or "")
