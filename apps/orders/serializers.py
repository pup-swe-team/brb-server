from django.utils import timezone
from rest_framework import serializers

from .models import Order


class BorrowRequestSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        if attrs["start_date"] < timezone.localdate():
            raise serializers.ValidationError(
                {"start_date": "Start date must be today or later."}
            )
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "End date must be on or after start date."}
            )
        return attrs


class BorrowRequestResultSerializer(serializers.ModelSerializer):
    listing_id = serializers.IntegerField(read_only=True)
    borrower_id = serializers.IntegerField(read_only=True)
    status = serializers.CharField(source="status.name", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "listing_id",
            "borrower_id",
            "start_date",
            "end_date",
            "status",
        ]
