from rest_framework import serializers

from .models import AdminAccessLog


class AdminAccessLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for immutable admin audit log entries (CP-1106)."""

    admin_email = serializers.ReadOnlyField(source="admin.email")
    admin_name = serializers.ReadOnlyField(source="admin.full_name")

    class Meta:
        model = AdminAccessLog
        fields = [
            "id",
            "action",
            "target_type",
            "target_id",
            "details",
            "admin",
            "admin_email",
            "admin_name",
            "document",
            "ip_address",
            "accessed_at",
        ]
        read_only_fields = fields
