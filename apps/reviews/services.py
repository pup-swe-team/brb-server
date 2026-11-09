from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Review


@transaction.atomic
def admin_remove_review(*, review_id: int) -> None:
    """Soft-delete a review without removing its order or report links (CP-1102)."""
    review = get_object_or_404(Review.objects.select_for_update(), pk=review_id)
    if review.deleted_at is None:
        review.deleted_at = timezone.now()
        review.save(update_fields=["deleted_at"])
