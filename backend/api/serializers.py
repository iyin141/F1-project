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


class ReadinessSerializer(serializers.Serializer):
    can_proceed = serializers.BooleanField()
    available_data = serializers.ListField(child=serializers.CharField())
    unavailable_data = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField(required=False, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)


class DriverStandingsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    drivers = DriverStandingSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)


class ConstructorStandingsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    constructors = ConstructorSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)


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
    can_proceed = serializers.BooleanField(required=False)
    available_data = serializers.ListField(child=serializers.CharField(), required=False)
    unavailable_data = serializers.ListField(child=serializers.CharField(), required=False)
    message = serializers.CharField(required=False, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)


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
    lap_a = serializers.IntegerField(min_value=1, allow_null=True)
    lap_b = serializers.IntegerField(min_value=1, allow_null=True)
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
    can_proceed = serializers.BooleanField(required=False)
    available_data = serializers.ListField(child=serializers.CharField(), required=False)
    unavailable_data = serializers.ListField(child=serializers.CharField(), required=False)
    message = serializers.CharField(required=False, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)


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
    flag = serializers.CharField(allow_null=True)
    scope = serializers.CharField(allow_null=True)
    sector = serializers.IntegerField(allow_null=True)
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
    stint = serializers.IntegerField(allow_null=True)
    track_status = serializers.CharField(allow_null=True)
    lap_time_seconds = serializers.FloatField(allow_null=True)
    is_fastest_lap_overall = serializers.BooleanField(default=False)
    is_fastest_lap_of_lap_number = serializers.BooleanField(default=False)


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


# ============================================================================
# Driver Career & Season Serializers
# ============================================================================


class DriverCareerSeasonSerializer(serializers.Serializer):
    """Single season row in a driver's career."""

    year = serializers.IntegerField(min_value=1950)
    races = serializers.IntegerField(default=0)
    wins = serializers.IntegerField(default=0)
    podiums = serializers.IntegerField(default=0)
    champion = serializers.BooleanField(default=False)


class DriverCareerTotalsSerializer(serializers.Serializer):
    """Career totals across all seasons."""

    total_wins = serializers.IntegerField(default=0)
    total_podiums = serializers.IntegerField(default=0)
    championships = serializers.IntegerField(default=0)


class DriverCareerResponseSerializer(serializers.Serializer):
    """Driver career summary response."""

    driver_code = serializers.CharField()
    driver_name = serializers.CharField(allow_null=True)
    nationality = serializers.CharField(allow_null=True)
    career = DriverCareerSeasonSerializer(many=True)
    career_totals = DriverCareerTotalsSerializer()
    readiness = ReadinessSerializer(required=False, allow_null=True)


class DriverRoundResultSerializer(serializers.Serializer):
    """Single round result for a driver in a season."""

    year = serializers.IntegerField(min_value=1950)
    round = serializers.IntegerField(min_value=1)
    race_name = serializers.CharField()
    location = serializers.CharField()
    race_date = serializers.CharField(allow_null=True)
    grid_position = serializers.IntegerField(allow_null=True)
    finish_position = serializers.IntegerField(allow_null=True)
    points = serializers.FloatField(default=0)
    status = serializers.CharField(allow_null=True)
    fastest_lap = serializers.BooleanField(default=False)
    laps_completed = serializers.IntegerField(allow_null=True)
    qualifying_position = serializers.IntegerField(allow_null=True)
    qualifying_time = serializers.CharField(allow_null=True)
    sprint_position = serializers.IntegerField(allow_null=True, required=False)
    sprint_points = serializers.FloatField(allow_null=True, required=False)
    sprint_status = serializers.CharField(allow_null=True, required=False)
    sprint_grid = serializers.IntegerField(allow_null=True, required=False)
    sprint_laps = serializers.IntegerField(allow_null=True, required=False)
    sprint_fastest_lap = serializers.BooleanField(allow_null=True, required=False)


class DriverSeasonResponseSerializer(serializers.Serializer):
    """Driver season breakdown response."""

    driver_code = serializers.CharField()
    driver_name = serializers.CharField(allow_null=True)
    year = serializers.IntegerField(min_value=1950)
    total_races = serializers.IntegerField(min_value=0, default=0)
    sprint_weekends = serializers.IntegerField(min_value=0, default=0)
    races = DriverRoundResultSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)


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
