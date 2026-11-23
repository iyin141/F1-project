"""Response shapes for the schema only; views return plain dicts built in service.py."""
from rest_framework import serializers


class TrackMapResponseSerializer(serializers.Serializer):
    meta = serializers.DictField()
    points = serializers.DictField(child=serializers.ListField(child=serializers.FloatField()), help_text="Columnar x, y, z (1/10 m) and distance (m)")
    corners = serializers.ListField(child=serializers.DictField(), help_text="number, letter, angle, distance, x, y")
    mini_sectors = serializers.DictField(help_text="Chosen scheme: boundaries (m) and, for corners, labels")
    drs_zones = serializers.ListField(child=serializers.DictField(), help_text="start_m, end_m")


class MiniSectorsResponseSerializer(serializers.Serializer):
    meta = serializers.DictField()
    boundaries = serializers.ListField(child=serializers.FloatField())
    labels = serializers.ListField(child=serializers.CharField())
    drivers = serializers.DictField(help_text="Per driver: lap_number, lap_time, lap_time_source, sector_times")
    fastest_per_sector = serializers.ListField(child=serializers.DictField())
    gaps = serializers.DictField(help_text="Per driver: seconds behind the fastest driver in each sector")


class DeltaResponseSerializer(serializers.Serializer):
    meta = serializers.DictField()
    ref = serializers.DictField()
    cmp = serializers.DictField()
    distance = serializers.ListField(child=serializers.FloatField())
    delta = serializers.ListField(child=serializers.FloatField(), help_text="Seconds; positive means cmp is slower than ref")


class PendingSerializer(serializers.Serializer):
    status = serializers.CharField()
    task_key = serializers.CharField()
    detail = serializers.CharField()
