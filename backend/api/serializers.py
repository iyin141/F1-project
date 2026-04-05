from rest_framework import serializers


class RaceSerializer(serializers.Serializer):
    round = serializers.IntegerField(min_value=1)
    name = serializers.CharField()
    date = serializers.CharField(allow_null=True)
    location = serializers.CharField()
    country = serializers.CharField()


class DriverStandingSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)
    constructor = serializers.CharField()


class ConstructorSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    constructor_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)


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


class RaceResultsSerializer(serializers.Serializer):
    qualifying = QualifyingResultSerializer(many=True)
    race = RaceResultSerializer(many=True)


class PracticeResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_code = serializers.CharField()
    team = serializers.CharField()
    lap_time = serializers.CharField(allow_null=True)
    lap_number = serializers.IntegerField(allow_null=True)


class LapAnalysisRowSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    lap_number = serializers.IntegerField(allow_null=True)
    lap_time = serializers.CharField(allow_null=True)
    sector1 = serializers.CharField(allow_null=True)
    sector2 = serializers.CharField(allow_null=True)
    sector3 = serializers.CharField(allow_null=True)
    compound = serializers.CharField(allow_null=True)
    stint = serializers.IntegerField(allow_null=True)
    is_personal_best = serializers.BooleanField()


class LapAnalysisMetaSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    round = serializers.IntegerField(min_value=1)
    session = serializers.CharField()
    row_count = serializers.IntegerField(min_value=0)
    limit_max = serializers.IntegerField(min_value=1)


class LapAnalysisFiltersSerializer(serializers.Serializer):
    driver = serializers.CharField(allow_null=True)
    limit = serializers.IntegerField(allow_null=True)


class LapAnalysisResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = LapAnalysisFiltersSerializer()
    data = LapAnalysisRowSerializer(many=True)


class StintAnalysisRowSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    stint_number = serializers.IntegerField(allow_null=True)
    compound = serializers.CharField(allow_null=True)
    lap_start = serializers.IntegerField(allow_null=True)
    lap_end = serializers.IntegerField(allow_null=True)
    total_laps = serializers.IntegerField(min_value=0)
    median_lap_seconds = serializers.FloatField(allow_null=True)
    min_lap_seconds = serializers.FloatField(allow_null=True)
    max_lap_seconds = serializers.FloatField(allow_null=True)


class StintAnalysisResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = LapAnalysisFiltersSerializer()
    data = StintAnalysisRowSerializer(many=True)


class PaceAnalysisRowSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    laps_completed = serializers.IntegerField(min_value=0)
    session_median_lap_seconds = serializers.FloatField(allow_null=True)
    session_best_lap_seconds = serializers.FloatField(allow_null=True)
    consistency_stddev_seconds = serializers.FloatField(allow_null=True)
    pace_improvement_seconds = serializers.FloatField(allow_null=True)


class PaceAnalysisResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = LapAnalysisFiltersSerializer()
    data = PaceAnalysisRowSerializer(many=True)


class TelemetryAnalysisPointSerializer(serializers.Serializer):
    time_seconds = serializers.FloatField(allow_null=True)
    distance_m = serializers.FloatField(allow_null=True)
    speed_kph = serializers.FloatField(allow_null=True)
    throttle_pct = serializers.FloatField(allow_null=True)
    brake = serializers.BooleanField()
    rpm = serializers.IntegerField(allow_null=True)
    gear = serializers.IntegerField(allow_null=True)


class TelemetryAnalysisFiltersSerializer(serializers.Serializer):
    driver = serializers.CharField()
    lap = serializers.IntegerField(min_value=1)
    limit_points = serializers.IntegerField(min_value=1)
    stride = serializers.IntegerField(min_value=1)
    sector_start = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)
    sector_end = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)


class TelemetryAnalysisResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = TelemetryAnalysisFiltersSerializer()
    data = TelemetryAnalysisPointSerializer(many=True)


class TelemetryOverlayTraceSerializer(serializers.Serializer):
    driver = serializers.CharField()
    lap = serializers.IntegerField(min_value=1)
    data = TelemetryAnalysisPointSerializer(many=True)


class TelemetryOverlayFiltersSerializer(serializers.Serializer):
    driver_a = serializers.CharField()
    driver_b = serializers.CharField()
    lap_a = serializers.IntegerField(min_value=1)
    lap_b = serializers.IntegerField(min_value=1)
    limit_points = serializers.IntegerField(min_value=1)
    stride = serializers.IntegerField(min_value=1)
    sector_start = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)
    sector_end = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)


class TelemetryOverlayResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = TelemetryOverlayFiltersSerializer()
    traces = TelemetryOverlayTraceSerializer(many=True)


class TelemetrySummaryFiltersSerializer(serializers.Serializer):
    driver = serializers.CharField()
    lap = serializers.IntegerField(min_value=1)
    stride = serializers.IntegerField(min_value=1)
    sector_start = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)
    sector_end = serializers.IntegerField(min_value=1, max_value=3, allow_null=True)


class TelemetrySummaryPayloadSerializer(serializers.Serializer):
    max_speed_kph = serializers.FloatField(allow_null=True)
    braking_zones = serializers.IntegerField(min_value=0)
    throttle_on_percentage = serializers.FloatField(allow_null=True)
    samples = serializers.IntegerField(min_value=0)


class TelemetrySummaryResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = TelemetrySummaryFiltersSerializer()
    summary = TelemetrySummaryPayloadSerializer()


class TyreStrategyRowSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    stint_number = serializers.IntegerField(allow_null=True)
    compound = serializers.CharField(allow_null=True)
    lap_start = serializers.IntegerField(allow_null=True)
    lap_end = serializers.IntegerField(allow_null=True)
    laps_in_stint = serializers.IntegerField(min_value=0)
    avg_lap_seconds = serializers.FloatField(allow_null=True)
    median_lap_seconds = serializers.FloatField(allow_null=True)
    degradation_seconds = serializers.FloatField(allow_null=True)


class TyreStrategyResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = LapAnalysisFiltersSerializer()
    data = TyreStrategyRowSerializer(many=True)


class SectorAnalysisRowSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    laps_count = serializers.IntegerField(min_value=0)
    best_sector1_seconds = serializers.FloatField(allow_null=True)
    best_sector2_seconds = serializers.FloatField(allow_null=True)
    best_sector3_seconds = serializers.FloatField(allow_null=True)
    median_sector1_seconds = serializers.FloatField(allow_null=True)
    median_sector2_seconds = serializers.FloatField(allow_null=True)
    median_sector3_seconds = serializers.FloatField(allow_null=True)
    best_lap_seconds = serializers.FloatField(allow_null=True)
    theoretical_best_lap_seconds = serializers.FloatField(allow_null=True)
    delta_to_theoretical_seconds = serializers.FloatField(allow_null=True)


class SectorAnalysisResponseSerializer(serializers.Serializer):
    meta = LapAnalysisMetaSerializer()
    filters_applied = LapAnalysisFiltersSerializer()
    data = SectorAnalysisRowSerializer(many=True)


# ============================================================================
# Base Response Serializers for Unified Service (used by all extractors)
# ============================================================================


class UnifiedMetaSerializer(serializers.Serializer):
    """Standard metadata for all unified service responses."""

    year = serializers.IntegerField(min_value=1950)
    round = serializers.IntegerField(min_value=1, max_value=24)
    session = serializers.CharField(max_length=10)
    row_count = serializers.IntegerField(min_value=0)
    extracted_at = serializers.DateTimeField()
    limit_max = serializers.IntegerField(min_value=1)


class UnifiedFiltersSerializer(serializers.Serializer):
    """Standard filters applied for all unified service responses."""

    driver = serializers.CharField(max_length=3, allow_null=True)
    limit = serializers.IntegerField(min_value=1, allow_null=True)


class UnifiedBaseResponseSerializer(serializers.Serializer):
    """Base response structure for all unified service extractors."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = serializers.ListField()  # Subclasses override with specific row serializer


# ============================================================================
# Specialized Response Serializers for upcoming extractors
# ============================================================================


class WeatherRowSerializer(serializers.Serializer):
    """Single weather snapshot row."""

    lap_number = serializers.IntegerField(allow_null=True)
    driver_code = serializers.CharField(allow_null=True)
    track_temp_c = serializers.FloatField(allow_null=True)
    air_temp_c = serializers.FloatField(allow_null=True)
    humidity_pct = serializers.FloatField(allow_null=True)
    wind_speed_ms = serializers.FloatField(allow_null=True)
    wind_direction_deg = serializers.FloatField(allow_null=True)
    rainfall = serializers.BooleanField(default=False)


class WeatherResponseSerializer(serializers.Serializer):
    """Weather data response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = WeatherRowSerializer(many=True)


class PitStopRowSerializer(serializers.Serializer):
    """Single pit stop row."""

    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    stop_number = serializers.IntegerField(min_value=1)
    lap_in = serializers.IntegerField(min_value=1)
    lap_out = serializers.IntegerField(allow_null=True)
    stop_duration_seconds = serializers.FloatField(allow_null=True)
    compound_in = serializers.CharField(allow_null=True)
    compound_out = serializers.CharField(allow_null=True)
    time_gain_loss_seconds = serializers.FloatField(allow_null=True)


class PitStopResponseSerializer(serializers.Serializer):
    """Pit stop strategy response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = PitStopRowSerializer(many=True)


class IncidentRowSerializer(serializers.Serializer):
    """Single incident/message row."""

    lap_number = serializers.IntegerField(allow_null=True)
    message_type = serializers.CharField()
    drivers_involved = serializers.ListField(child=serializers.CharField())
    message_text = serializers.CharField()
    timestamp_seconds = serializers.FloatField(allow_null=True)
    impact_on_race = serializers.CharField(allow_null=True)


class IncidentResponseSerializer(serializers.Serializer):
    """Incident timeline response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = IncidentRowSerializer(many=True)


class PositionChangeRowSerializer(serializers.Serializer):
    """Single position change row."""

    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    lap_number = serializers.IntegerField(min_value=1)
    position = serializers.IntegerField(min_value=1)
    position_change = serializers.IntegerField(allow_null=True)
    gap_to_leader_seconds = serializers.FloatField(allow_null=True)
    gap_to_ahead_seconds = serializers.FloatField(allow_null=True)


class PositionResponseSerializer(serializers.Serializer):
    """Position changes response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = PositionChangeRowSerializer(many=True)


class DRSRowSerializer(serializers.Serializer):
    """Single DRS activation row."""

    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    lap_number = serializers.IntegerField(min_value=1)
    drs_available = serializers.BooleanField()
    drs_activated = serializers.BooleanField()
    gap_behind_seconds = serializers.FloatField(allow_null=True)
    performance_delta_ms = serializers.FloatField(allow_null=True)


class DRSResponseSerializer(serializers.Serializer):
    """DRS activation response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = DRSRowSerializer(many=True)


class TrackStatusRowSerializer(serializers.Serializer):
    """Single track status change row."""

    lap_number = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    status_duration_laps = serializers.IntegerField(allow_null=True)
    cause = serializers.CharField(allow_null=True)
    affected_zone = serializers.CharField(allow_null=True)


class TrackStatusResponseSerializer(serializers.Serializer):
    """Track status timeline response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = TrackStatusRowSerializer(many=True)


class TyreDegradationRowSerializer(serializers.Serializer):
    """Single tyre degradation data row."""

    driver_code = serializers.CharField()
    driver_number = serializers.IntegerField(allow_null=True)
    compound = serializers.CharField(allow_null=True)
    lap_number = serializers.IntegerField(min_value=1)
    lap_time_seconds = serializers.FloatField(allow_null=True)
    degradation_vs_first_lap_ms = serializers.FloatField(allow_null=True)
    tyre_age_laps = serializers.IntegerField(min_value=0)


class TyreDegradationResponseSerializer(serializers.Serializer):
    """Tyre degradation curves response structure."""

    meta = UnifiedMetaSerializer()
    filters_applied = UnifiedFiltersSerializer()
    data = TyreDegradationRowSerializer(many=True)
