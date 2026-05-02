from django.db import models
from django.db.models import Q


class Race(models.Model):
	class Status(models.TextChoices):
		UPCOMING = "upcoming", "Upcoming"
		COMPLETED = "completed", "Completed"
		PROCESSING = "processing", "Processing"
		FAILED = "failed", "Failed"

	season = models.PositiveSmallIntegerField()
	round_number = models.PositiveSmallIntegerField()
	race_name = models.CharField(max_length=255)
	circuit_name = models.CharField(max_length=255)
	country = models.CharField(max_length=120)
	location = models.CharField(max_length=120, null=True, blank=True)
	race_date = models.DateField()
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
	fastf1_event_name = models.CharField(max_length=255, null=True, blank=True)
	populated_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=["season", "round_number"], name="uniq_race_season_round"),
			models.CheckConstraint(condition=Q(season__gte=1950), name="race_season_gte_1950"),
			models.CheckConstraint(condition=Q(round_number__gte=1), name="race_round_gte_1"),
		]
		indexes = [
			models.Index(fields=["season", "status"], name="idx_race_season_status"),
			models.Index(fields=["race_date"], name="idx_race_date"),
		]


class RaceResult(models.Model):
	race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="results")
	driver_code = models.CharField(max_length=3)
	driver_number = models.PositiveSmallIntegerField(null=True, blank=True)
	driver_name = models.CharField(max_length=120)
	constructor_name = models.CharField(max_length=120)
	grid_position = models.PositiveSmallIntegerField(null=True, blank=True)
	finish_position = models.PositiveSmallIntegerField(null=True, blank=True)
	points = models.DecimalField(max_digits=6, decimal_places=2, default=0)
	status_text = models.CharField(max_length=120, null=True, blank=True)
	fastest_lap = models.BooleanField(default=False)
	laps_completed = models.PositiveSmallIntegerField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=["race", "driver_code"], name="uniq_result_race_driver"),
			models.CheckConstraint(condition=Q(points__gte=0), name="result_points_gte_0"),
		]
		indexes = [
			models.Index(fields=["race", "finish_position"], name="idx_result_race_finish"),
			models.Index(fields=["race", "constructor_name"], name="idx_result_race_constructor"),
			models.Index(fields=["driver_code"], name="idx_result_driver_code"),
		]


class StintData(models.Model):
	race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="stints")
	driver_code = models.CharField(max_length=3)
	driver_number = models.PositiveSmallIntegerField(null=True, blank=True)
	stint_number = models.PositiveSmallIntegerField()
	compound = models.CharField(max_length=20, null=True, blank=True)
	lap_start = models.PositiveSmallIntegerField()
	lap_end = models.PositiveSmallIntegerField()
	laps_in_stint = models.PositiveSmallIntegerField()
	avg_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	median_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	min_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	max_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	degradation_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	pit_in_lap = models.PositiveSmallIntegerField(null=True, blank=True)
	pit_out_lap = models.PositiveSmallIntegerField(null=True, blank=True)
	computed_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=["race", "driver_code", "stint_number"],
				name="uniq_stint_race_driver_stint",
			),
			models.CheckConstraint(condition=Q(lap_start__gte=1), name="stint_lap_start_gte_1"),
			models.CheckConstraint(condition=Q(lap_end__gte=1), name="stint_lap_end_gte_1"),
			models.CheckConstraint(condition=Q(laps_in_stint__gte=1), name="stint_laps_count_gte_1"),
		]
		indexes = [
			models.Index(fields=["race", "driver_code"], name="idx_stint_race_driver"),
			models.Index(fields=["race", "compound"], name="idx_stint_race_compound"),
			models.Index(fields=["race", "lap_start"], name="idx_stint_race_lap_start"),
		]


class DriverMetric(models.Model):
	race = models.ForeignKey(
		Race,
		on_delete=models.CASCADE,
		related_name="driver_metrics",
		null=True,
		blank=True,
	)
	season = models.PositiveSmallIntegerField()
	driver_code = models.CharField(max_length=3)
	consistency_score = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	raw_stddev_seconds = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	normalized_stddev_seconds = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	normalized_cv = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	valid_lap_count = models.PositiveSmallIntegerField(default=0)
	excluded_lap_count = models.PositiveSmallIntegerField(default=0)
	excluded_by_reason = models.JSONField(default=dict, blank=True)
	avg_pace_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	avg_qualifying_position = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	avg_race_position = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	race_position = models.PositiveSmallIntegerField(null=True, blank=True)
	qualifying_position = models.PositiveSmallIntegerField(null=True, blank=True)
	value_index = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	pace_rank = models.PositiveSmallIntegerField(null=True, blank=True)
	consistency_rank = models.PositiveSmallIntegerField(null=True, blank=True)
	insufficient_data = models.BooleanField(default=False)
	season_aggregate = models.BooleanField(default=False)
	formula_version = models.CharField(max_length=40, default="consistency_v1")
	computed_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.CheckConstraint(condition=Q(season__gte=1950), name="metric_season_gte_1950"),
			models.UniqueConstraint(
				fields=["race", "driver_code"],
				condition=Q(season_aggregate=False),
				name="uniq_metric_race_driver_non_agg",
			),
			models.UniqueConstraint(
				fields=["season", "driver_code"],
				condition=Q(season_aggregate=True),
				name="uniq_metric_season_driver_agg",
			),
		]
		indexes = [
			models.Index(fields=["race", "consistency_score"], name="idx_metric_race_consistency"),
			models.Index(fields=["season", "value_index"], name="idx_metric_season_value"),
			models.Index(fields=["driver_code", "season"], name="idx_metric_driver_season"),
		]


class SectorAggregate(models.Model):
	race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="sector_aggregates")
	driver_code = models.CharField(max_length=3)
	driver_number = models.PositiveSmallIntegerField(null=True, blank=True)
	laps_count = models.PositiveSmallIntegerField(default=0)
	best_sector1_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	best_sector2_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	best_sector3_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	median_sector1_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	median_sector2_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	median_sector3_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	best_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	theoretical_best_lap_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	delta_to_theoretical_seconds = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
	computed_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=["race", "driver_code"], name="uniq_sector_race_driver"),
		]
		indexes = [
			models.Index(fields=["race", "theoretical_best_lap_seconds"], name="idx_sector_race_theoretical"),
			models.Index(fields=["driver_code"], name="idx_sector_driver_code"),
		]


class DriverSeasonSummary(models.Model):
	"""
	Pre-aggregated season stats per driver.
	Populated after persisting race results for a round.
	Avoids re-computing career totals from raw results.
	"""

	driver_code = models.CharField(max_length=3)
	year = models.PositiveSmallIntegerField()
	constructor = models.CharField(max_length=120, null=True, blank=True)
	position = models.PositiveSmallIntegerField(null=True, blank=True)
	points = models.DecimalField(max_digits=6, decimal_places=2, default=0)
	wins = models.PositiveSmallIntegerField(default=0)
	podiums = models.PositiveSmallIntegerField(default=0)
	poles = models.PositiveSmallIntegerField(default=0)
	fastest_laps = models.PositiveSmallIntegerField(default=0)
	races_entered = models.PositiveSmallIntegerField(default=0)
	dnfs = models.PositiveSmallIntegerField(default=0)
	computed_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=["driver_code", "year"], name="uniq_driver_season"),
			models.CheckConstraint(condition=Q(year__gte=1950), name="season_summary_year_gte_1950"),
		]
		indexes = [
			models.Index(fields=["driver_code"], name="idx_season_summary_driver"),
			models.Index(fields=["driver_code", "year"], name="idx_season_summary_driver_year"),
			models.Index(fields=["year", "position"], name="idx_season_yr_position"),
		]
