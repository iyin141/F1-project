"""Serializers for schedule domain."""
from rest_framework import serializers


class RaceSerializer(serializers.Serializer):
    round = serializers.IntegerField(min_value=1)
    name = serializers.CharField()
    date = serializers.CharField(allow_null=True)
    location = serializers.CharField()
    country = serializers.CharField()
    event_format = serializers.CharField(required=False, allow_null=True)
    session1 = serializers.CharField(required=False, allow_null=True)
    session1_date_utc = serializers.DateTimeField(required=False, allow_null=True)
    session2 = serializers.CharField(required=False, allow_null=True)
    session2_date_utc = serializers.DateTimeField(required=False, allow_null=True)
    session3 = serializers.CharField(required=False, allow_null=True)
    session3_date_utc = serializers.DateTimeField(required=False, allow_null=True)
    session4 = serializers.CharField(required=False, allow_null=True)
    session4_date_utc = serializers.DateTimeField(required=False, allow_null=True)
    session5 = serializers.CharField(required=False, allow_null=True)
    session5_date_utc = serializers.DateTimeField(required=False, allow_null=True)
