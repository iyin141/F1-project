"""Serializers for constructor standings responses."""
from rest_framework import serializers


class ConstructorSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    constructor_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)


class ReadinessSerializer(serializers.Serializer):
    can_proceed = serializers.BooleanField()
    available_data = serializers.ListField(child=serializers.CharField())
    unavailable_data = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField(required=False, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)


class ConstructorStandingsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    constructors = ConstructorSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)
