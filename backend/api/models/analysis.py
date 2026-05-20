from django.db import models
from django.db.models import Q


class DriverLapAnalysis(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    driver_code = models.CharField(max_length=3, null=True, blank=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "driver_lap_analysis"
        constraints = [
            # Partial enforcement: rows where driver_code is non-null must be unique per (year, round, session, driver_code).
            # Nullable driver_code rows are guarded at the application layer via update_or_create.
            models.UniqueConstraint(
                fields=["year", "round_number", "session", "driver_code"],
                name="uniq_driver_lap_analysis_year_round_session_driver",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="driver_lap_analysis_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="driver_lap_analysis_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_dla_year_round"),
            models.Index(fields=["year", "round_number", "driver_code"], name="idx_dla_year_round_driver"),
        ]

    def __str__(self):
        return f"DriverLapAnalysis({self.year}, R{self.round_number}, {self.session}, {self.driver_code})"


class DriverTelemetry(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    driver_code = models.CharField(max_length=3, null=True, blank=True)
    lap = models.PositiveSmallIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "driver_telemetry"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session", "driver_code"],
                name="uniq_driver_telemetry_year_round_session_driver",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="driver_telemetry_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="driver_telemetry_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_dt_year_round"),
        ]

    def __str__(self):
        return f"DriverTelemetry({self.year}, R{self.round_number}, {self.session}, {self.driver_code}, lap={self.lap})"
