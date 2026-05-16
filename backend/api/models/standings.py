from django.db import models
from django.db.models import Q



class DriverStandings(models.Model):
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    driver_code = models.CharField(max_length=3, null=True, blank=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "driver_standings"
        # Three usage patterns:
        #   year=2026, driver_code=NULL  → full grid standings for that season
        #   year=2026, driver_code='VER' → single driver in that season
        #   year=NULL,  driver_code='VER' → career history for driver
        # Nullable keys mean the DB UniqueConstraint only enforces when both are non-null.
        # All inserts/updates must use update_or_create in service layer.
        constraints = [
            models.UniqueConstraint(
                fields=["year", "driver_code"],
                name="uniq_driver_standings_year_driver",
            ),
            models.CheckConstraint(
                condition=Q(year__gte=1950) | Q(year__isnull=True),
                name="driver_standings_year_gte_1950_or_null",
            ),
        ]
        indexes = [
            models.Index(fields=["year"], name="idx_driver_standings_year"),
            models.Index(fields=["driver_code"], name="idx_driver_standings_driver"),
        ]

    def __str__(self):
        return f"DriverStandings(year={self.year}, driver={self.driver_code})"


class ConstructorStandings(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "constructor_standings"
        constraints = [
            models.CheckConstraint(condition=Q(year__gte=1950), name="constructor_standings_year_gte_1950"),
        ]
        indexes = []

    def __str__(self):
        return f"ConstructorStandings({self.year})"


class DriverCareer(models.Model):
    """
    Stores the full career history for a single driver across all seasons.

    Natural key: driver_code (unique).
    Payload schema:
        {
            "driver_name": str,
            "nationality": str,
            "career": [{year, constructor, position, points, wins, podiums, ...}],
            "career_totals": {championships, wins, podiums, poles, fastest_laps, ...},
        }
    """
    driver_code = models.CharField(max_length=3, unique=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "driver_career"
        indexes = []

    def __str__(self):
        return f"DriverCareer({self.driver_code})"


class DriverSeasonBreakdown(models.Model):
    """
    Stores the race-by-race breakdown for one driver in one season.

    Natural key: (driver_code, year).
    Payload schema:
        {
            "driver_name": str,
            "constructor": str,
            "final_position": int | None,
            "final_points": float | None,
            "races": [{round, race_name, location, race_date, finish_position, ...}],
        }
    """
    driver_code = models.CharField(max_length=3)
    year = models.PositiveSmallIntegerField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "driver_season_breakdown"
        constraints = [
            models.UniqueConstraint(
                fields=["driver_code", "year"],
                name="uniq_driver_season_breakdown_code_year",
            ),
            models.CheckConstraint(
                condition=Q(year__gte=1950),
                name="driver_season_breakdown_year_gte_1950",
            ),
        ]
        indexes = [
            models.Index(fields=["driver_code"], name="idx_drv_season_brkdown_code"),
            models.Index(fields=["year"], name="idx_drv_season_brkdown_year"),
        ]

    def __str__(self):
        return f"DriverSeasonBreakdown({self.driver_code}, {self.year})"
