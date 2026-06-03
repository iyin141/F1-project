from django.db import models
from django.db.models import Q


class WeatherData(models.Model):
    """Weather data for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "weather_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_weather_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="weather_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="weather_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_wd_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_wd_year_round"),
        ]

    def __str__(self):
        return f"WeatherData({self.year}, R{self.round_number}, {self.session})"


class PitStopData(models.Model):
    """Pit stop records for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "pit_stop_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_pit_stop_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="pit_stop_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="pit_stop_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_ps_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_ps_year_round"),
        ]

    def __str__(self):
        return f"PitStopData({self.year}, R{self.round_number}, {self.session})"


class IncidentData(models.Model):
    """Incidents/messages for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "incident_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_incident_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="incident_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="incident_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_id_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_id_year_round"),
        ]

    def __str__(self):
        return f"IncidentData({self.year}, R{self.round_number}, {self.session})"


class PositionData(models.Model):
    """Position changes for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "position_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_position_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="position_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="position_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_pd_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_pd_year_round"),
        ]

    def __str__(self):
        return f"PositionData({self.year}, R{self.round_number}, {self.session})"


class DRSData(models.Model):
    """DRS activations for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "drs_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_drs_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="drs_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="drs_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_drs_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_drs_year_round"),
        ]

    def __str__(self):
        return f"DRSData({self.year}, R{self.round_number}, {self.session})"


class TrackStatusData(models.Model):
    """Track status changes for a session stored as serialized JSONB payload."""
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "track_status_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_track_status_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="track_status_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="track_status_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number", "session"], name="idx_ts_year_round_session"),
            models.Index(fields=["year", "round_number"], name="idx_ts_year_round"),
        ]

    def __str__(self):
        return f"TrackStatusData({self.year}, R{self.round_number}, {self.session})"
