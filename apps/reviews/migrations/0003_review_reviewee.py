import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_reviewee(apps, schema_editor):
    """
    A review is always mutual: whichever party is not the reviewer receives
    it, so the counterparty is the order's lender when the order's borrower
    wrote the review, and vice versa.
    """
    Review = apps.get_model("reviews", "Review")
    for review in Review.objects.select_related("order__listing").iterator():
        if review.reviewee_id is not None:
            continue
        lender_id = review.order.listing.lender_id
        borrower_id = review.order.borrower_id
        review.reviewee_id = borrower_id if review.reviewer_id == lender_id else lender_id
        review.save(update_fields=["reviewee"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reviews", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="reviewee",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="received_reviews",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_reviewee, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="review",
            name="reviewee",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="received_reviews",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.CheckConstraint(
                condition=models.Q(("reviewer", models.F("reviewee")), _negated=True),
                name="review_reviewer_not_reviewee",
            ),
        ),
    ]
