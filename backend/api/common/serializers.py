from rest_framework import serializers


class ReadinessSerializer(serializers.Serializer):
    can_proceed = serializers.BooleanField()
    available_data = serializers.ListField(child=serializers.CharField())
    unavailable_data = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField(required=False, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)
