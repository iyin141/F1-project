"""Serializers for the drivers domain."""
from rest_framework import serializers
from api.common.serializers import ReadinessSerializer


# ReadinessSerializer moved to api.common.serializers

# --- Driver Standings ---

class DriverStandingSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)
    constructor = serializers.CharField()


class DriverStandingsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    drivers = DriverStandingSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)


# --- Driver Career ---

class DriverCareerSeasonSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1950)
    races = serializers.IntegerField(default=0)
    wins = serializers.IntegerField(default=0)
    podiums = serializers.IntegerField(default=0)
    champion = serializers.BooleanField(default=False)


class DriverCareerTotalsSerializer(serializers.Serializer):
    total_wins = serializers.IntegerField(default=0)
    total_podiums = serializers.IntegerField(default=0)
    championships = serializers.IntegerField(default=0)


class DriverCareerResponseSerializer(serializers.Serializer):
    driver_code = serializers.CharField()
    driver_name = serializers.CharField(allow_null=True)
    nationality = serializers.CharField(allow_null=True)
    career = DriverCareerSeasonSerializer(many=True)
    career_totals = DriverCareerTotalsSerializer()
    readiness = ReadinessSerializer(required=False, allow_null=True)


# --- Driver Season ---

class DriverRoundResultSerializer(serializers.Serializer):
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
    driver_code = serializers.CharField()
    driver_name = serializers.CharField(allow_null=True)
    year = serializers.IntegerField(min_value=1950)
    total_races = serializers.IntegerField(min_value=0, default=0)
    sprint_weekends = serializers.IntegerField(min_value=0, default=0)
    races = DriverRoundResultSerializer(many=True)
    readiness = ReadinessSerializer(required=False, allow_null=True)


# --- Phase 8: Driver Search & Sync ---

class DriverSearchResultSerializer(serializers.Serializer):
    """Serializer for individual driver search result."""
    driver_id = serializers.CharField()
    code = serializers.CharField(allow_null=True)
    number = serializers.CharField(allow_null=True)
    name = serializers.CharField()
    given_name = serializers.CharField()
    family_name = serializers.CharField()
    nationality = serializers.CharField(allow_null=True)
    dob = serializers.CharField(allow_null=True)
    seasons = serializers.ListField(child=serializers.IntegerField())


class DriverSearchResponseSerializer(serializers.Serializer):
    """Serializer for driver search API response."""
    query = serializers.CharField()
    year_filter = serializers.IntegerField(allow_null=True)
    results = DriverSearchResultSerializer(many=True)
    count = serializers.IntegerField(min_value=0)


class DriverSyncResponseSerializer(serializers.Serializer):
    """Serializer for driver sync API response."""
    year = serializers.IntegerField(allow_null=True)
    message = serializers.CharField()
    task_id = serializers.CharField(allow_null=True)
    status = serializers.CharField()  # "queued", "complete", or "failed"
    estimated_duration_minutes = serializers.IntegerField(allow_null=True, required=False)


# --- Phase 8b: Enhanced Search Endpoints ---

class DriverListItemSerializer(serializers.Serializer):
    """Single driver in season driver list."""
    driver_id = serializers.CharField()
    driver_code = serializers.CharField(allow_null=True)
    driver_name = serializers.CharField()
    nationality = serializers.CharField(allow_null=True)
    number = serializers.IntegerField(allow_null=True)
    seasons = serializers.ListField(child=serializers.IntegerField())


class DriverListResponseSerializer(serializers.Serializer):
    """Response for GET /api/drivers/search/?year=<year>."""
    year = serializers.IntegerField(min_value=1950)
    count = serializers.IntegerField(min_value=0)
    drivers = DriverListItemSerializer(many=True)


class DriverSearchMatchesSerializer(serializers.Serializer):
    """Highlight which fields matched the search query."""
    code = serializers.BooleanField()
    given_name = serializers.BooleanField()
    family_name = serializers.BooleanField()
    driver_id = serializers.BooleanField()


class DriverSearchByNameResultSerializer(serializers.Serializer):
    """Single driver result in search-by-name response."""
    driver_id = serializers.CharField()
    driver_code = serializers.CharField(allow_null=True)
    driver_name = serializers.CharField()
    nationality = serializers.CharField(allow_null=True)
    number = serializers.IntegerField(allow_null=True)
    seasons = serializers.ListField(child=serializers.IntegerField())
    matches = DriverSearchMatchesSerializer()


class DriverSearchByNameResponseSerializer(serializers.Serializer):
    """Response for GET /api/drivers/search-by-name/?q=<query>&year=<year>."""
    query = serializers.CharField()
    year = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField(min_value=0)
    results = DriverSearchByNameResultSerializer(many=True)
    message = serializers.CharField(allow_null=True)
