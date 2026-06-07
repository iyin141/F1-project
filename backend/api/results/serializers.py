"""Serializers for results domain."""
from rest_framework import serializers


class QualifyingResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    q1_time = serializers.CharField(allow_null=True)
    q2_time = serializers.CharField(allow_null=True)
    q3_time = serializers.CharField(allow_null=True)


class RaceResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    points = serializers.IntegerField(min_value=0)
    status = serializers.CharField()
    grid_position = serializers.IntegerField(allow_null=True)
    laps = serializers.IntegerField(min_value=0)
    gap = serializers.CharField(allow_null=True, required=False)
    fastest_lap = serializers.CharField(allow_null=True, required=False)
    fastest_lap_of_race = serializers.BooleanField(default=False)


class RaceResultsSerializer(serializers.Serializer):
   qualifying = QualifyingResultSerializer(many=True, required=False, default=list)
   race = RaceResultSerializer(many=True, required=False, default=list)


class PracticeResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    lap_time = serializers.CharField(allow_null=True)
    lap_number = serializers.IntegerField(allow_null=True)


class SprintResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    points = serializers.IntegerField(min_value=0, allow_null=True)
    status = serializers.CharField(allow_null=True)
    grid_position = serializers.IntegerField(allow_null=True)
    laps = serializers.IntegerField(min_value=0, allow_null=True)
    gap = serializers.CharField(allow_null=True, required=False)
    fastest_lap = serializers.CharField(allow_null=True, required=False)
    fastest_lap_of_sprint = serializers.BooleanField(default=False)


class SprintShootoutResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    q1_time = serializers.CharField(allow_null=True)
    q2_time = serializers.CharField(allow_null=True)
    q3_time = serializers.CharField(allow_null=True)
