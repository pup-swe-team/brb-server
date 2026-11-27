from rest_framework import serializers

from .constants import CONFIG_METADATA


class SystemConfigItemSerializer(serializers.Serializer):
    """Represents a single configuration parameter with metadata."""

    config_key = serializers.CharField()
    config_value = serializers.CharField()
    label = serializers.CharField()
    category = serializers.CharField()
    description = serializers.CharField()
    type = serializers.CharField()
    default_value = serializers.CharField()
    min_value = serializers.IntegerField(allow_null=True, required=False)
    max_value = serializers.IntegerField(allow_null=True, required=False)
    updated_by = serializers.CharField(allow_null=True, required=False)
    updated_at = serializers.DateTimeField(allow_null=True, required=False)


class SystemConfigUpdateSerializer(serializers.Serializer):
    """Validates an update to a single config parameter."""

    value = serializers.CharField(required=True)

    def validate_value(self, value: str) -> str:
        key = self.context.get("config_key")
        val_str = str(value).strip()
        if not val_str:
            raise serializers.ValidationError("Configuration value cannot be blank.")

        meta = CONFIG_METADATA.get(key)
        if meta and meta.get("type") == "integer":
            try:
                int_val = int(val_str)
            except ValueError:
                raise serializers.ValidationError("Value must be a valid integer.")
            min_val = meta.get("min")
            max_val = meta.get("max")
            if min_val is not None and int_val < min_val:
                raise serializers.ValidationError(
                    f"Value cannot be less than {min_val}."
                )
            if max_val is not None and int_val > max_val:
                raise serializers.ValidationError(
                    f"Value cannot be greater than {max_val}."
                )
        return val_str


class SystemConfigBulkUpdateSerializer(serializers.Serializer):
    """Validates bulk update of config parameters."""

    configs = serializers.DictField(
        child=serializers.CharField(),
        required=True,
    )

    def validate_configs(self, configs: dict[str, str]) -> dict[str, str]:
        if not configs:
            raise serializers.ValidationError("No configuration values provided.")

        validated = {}
        for key, value in configs.items():
            if key not in CONFIG_METADATA:
                raise serializers.ValidationError(
                    f"Unknown configuration parameter: '{key}'."
                )
            val_str = str(value).strip()
            if not val_str:
                raise serializers.ValidationError(f"Value for '{key}' cannot be blank.")

            meta = CONFIG_METADATA[key]
            if meta.get("type") == "integer":
                try:
                    int_val = int(val_str)
                except ValueError:
                    raise serializers.ValidationError(
                        f"Value for '{key}' must be an integer."
                    )
                min_val = meta.get("min")
                max_val = meta.get("max")
                if min_val is not None and int_val < min_val:
                    raise serializers.ValidationError(
                        f"Value for '{key}' cannot be less than {min_val}."
                    )
                if max_val is not None and int_val > max_val:
                    raise serializers.ValidationError(
                        f"Value for '{key}' cannot be greater than {max_val}."
                    )
            validated[key] = val_str
        return validated
