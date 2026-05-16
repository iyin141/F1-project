from django.db import models
from django.db.models import Q


class SeasonSchedule(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "season_schedule"
        constraints = [
            models.CheckConstraint(condition=Q(year__gte=1950), name="season_schedule_year_gte_1950"),
        ]
        indexes = [
            models.Index(fields=["year"], name="idx_season_schedule_year"),
        ]

    def __str__(self):
        return f"SeasonSchedule({self.year})"


class RaceResultData(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "race_results"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_race_result_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="race_result_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="race_result_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_rrd_year_round"),
        ]

    def __str__(self):
        return f"RaceResultData({self.year}, R{self.round_number}, {self.session})"


class QualifyingResultData(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "qualifying_results"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number"],
                name="uniq_qualifying_result_data_year_round",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="qualifying_result_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="qualifying_result_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_qrd_year_round"),
        ]

    def __str__(self):
        return f"QualifyingResultData({self.year}, R{self.round_number})"


class PracticeResultData(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "practice_results"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_practice_result_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="practice_result_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="practice_result_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_prd_year_round"),
        ]

    def __str__(self):
        return f"PracticeResultData({self.year}, R{self.round_number}, {self.session})"
