"""Response shapes for the schema only; views return plain dicts built in service.py."""
from rest_framework import serializers


class ChaosPendingSerializer(serializers.Serializer):
    status = serializers.CharField()
    task_key = serializers.CharField()
    detail = serializers.CharField()


class ModelBlockSerializer(serializers.Serializer):
    model = serializers.CharField(help_text="kumo_tabular_calibrated, kumo_tabular or beta_binomial")
    size = serializers.CharField()
    run_id = serializers.IntegerField()
    race_key = serializers.CharField()
    context_rows = serializers.IntegerField()
    calibration = serializers.CharField()
    calibrated = serializers.BooleanField()
    is_fallback = serializers.BooleanField(help_text="true when the baseline is served because no calibrated Kumo run exists")
    fallback_reason = serializers.CharField(allow_null=True)
    selected_by = serializers.CharField()
    interval = serializers.CharField()
    updated = serializers.CharField()


class RaceChaosSerializer(serializers.Serializer):
    meta = serializers.DictField()
    model = ModelBlockSerializer()
    targets = serializers.DictField(help_text="target -> probability, p10, p90 (race-level: at least one event)")
    chaos_index = serializers.FloatField(help_text="expected disruptive events: sum of the expected_events of index_targets")
    chaos_index_band = serializers.DictField()
    index_targets = serializers.ListField(child=serializers.CharField())
    expected_events = serializers.DictField(help_text="target -> value, p10, p90, source")
    factors = serializers.ListField(child=serializers.DictField(), help_text="largest differences from the circuit-type average")


class DriversChaosSerializer(serializers.Serializer):
    meta = serializers.DictField()
    model = ModelBlockSerializer()
    ranked_by = serializers.CharField()
    note = serializers.CharField()
    drivers = serializers.ListField(child=serializers.DictField())


class LapsChaosSerializer(serializers.Serializer):
    meta = serializers.DictField()
    model = ModelBlockSerializer()
    target = serializers.CharField()
    strip = serializers.ListField(child=serializers.FloatField(allow_null=True), help_text="probability per 5-lap window for `target`")
    windows = serializers.ListField(child=serializers.DictField())


class CircuitHistorySerializer(serializers.Serializer):
    circuit = serializers.DictField()
    summary = serializers.DictField()
    races = serializers.ListField(child=serializers.DictField())


class DriverProfileSerializer(serializers.Serializer):
    driver = serializers.CharField()
    last_team = serializers.CharField()
    seasons = serializers.ListField(child=serializers.IntegerField())
    races = serializers.IntegerField()
    label = serializers.CharField()
    tendencies = serializers.DictField()


class ModelPageSerializer(serializers.Serializer):
    current_runs = serializers.ListField(child=serializers.DictField())
    backtest = serializers.DictField(allow_null=True)


class CircuitListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    history_url = serializers.CharField()
    circuits = serializers.ListField(child=serializers.DictField(), help_text="slug, name, type, aliases, circuit_key, length_m, corners, stored")


class CircuitsSummarySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    circuits = serializers.ListField(child=serializers.DictField(), help_text="slug, name, type, summary{races, safety_car_rate, vsc_rate, red_flag_rate, any_neutralisation_rate, mean_mechanical_dnfs, mean_incident_dnfs}")
    unmatched_circuits = serializers.ListField(child=serializers.CharField(), help_text="circuit texts in stored races that match no known circuit")
    note = serializers.CharField()
