"""Serializers for constructor standings responses."""
from rest_framework import serializers
from api.common.serializers import ReadinessSerializer


class ConstructorSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    constructor_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)


# ReadinessSerializer moved to api.common.serializers

class ConstructorStandingsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    constructors = ConstructorSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)
