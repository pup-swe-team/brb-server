from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Review(models.Model):
    """
    Mutual 1-to-5 star rating and review after an order is Completed (FR9).
    Each participant (Borrower and Lender) may review once per order.
    """

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="given_reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating score from 1 to 5 stars",
    )
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @property
    def reviewee(self):
        """
        The counterparty being reviewed, derived from the order.

        An order has exactly two participants, borrower and lender, so the
        reviewee is always the party who did not write the review.
        """
        if self.reviewer_id == self.order.borrower_id:
            return self.order.listing.lender
        return self.order.borrower

    @property
    def reviewee_id(self):
        return self.reviewee.pk

    class Meta:
        db_table = "reviews"
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        constraints = (
            models.UniqueConstraint(
                fields=["order", "reviewer"],
                name="unique_order_reviewer",
            ),
        )

    def clean(self):
        if self.reviewee_id == self.reviewer_id:
            raise ValidationError("A reviewer cannot review themselves.")

    def __str__(self) -> str:
        return f"{self.rating}★ review by {self.reviewer.full_name} for {self.reviewee.full_name} on Order #{self.order_id}"
