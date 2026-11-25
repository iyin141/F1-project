from django.db import models


class CircuitProfile(models.Model):
    """Static circuit traits. Derivable fields come from trackmap.TrackGeometry; the rest from data/circuits.yaml
    (hand-curated, cited). Unknown stays NULL, never guessed."""

    TYPES = [("street", "street"), ("permanent", "permanent"), ("hybrid", "hybrid")]

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    locations = models.JSONField(default=list)  # FastF1 schedule `location` strings that map to this circuit
    circuit_key = models.IntegerField(null=True, blank=True)  # MultiViewer key = TrackGeometry.circuit_key
    circuit_type = models.CharField(max_length=12, choices=TYPES, null=True, blank=True)
    length_m = models.FloatField(null=True, blank=True)  # from TrackGeometry
    corners = models.PositiveSmallIntegerField(null=True, blank=True)  # from TrackGeometry
    wall_proximity = models.FloatField(null=True, blank=True)  # ordinal proxy 0 (run-offs) .. 1 (walls at the edge)
    overtaking_index = models.FloatField(null=True, blank=True)
    elevation_range_m = models.FloatField(null=True, blank=True)
    sources = models.JSONField(default=dict)  # field -> citation
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CircuitProfile({self.slug})"


class RaceEventLabel(models.Model):
    """One labelled event in a race. Race / driver-race / 5-lap-window targets are aggregated from these
    (api.chaos.labels.aggregate_labels), so there is one source of truth."""

    SC, VSC, RED = "sc", "vsc", "red_flag"
    SLOW_STOP, UNLUCKY_STOP = "slow_stop", "unlucky_stop"
    # DNF types are "dnf_<group>" with group from dnf_status_map.yaml

    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    lap = models.PositiveSmallIntegerField(null=True, blank=True)  # null = lap could not be resolved
    driver = models.CharField(max_length=8, blank=True, default="")  # 3-letter code, or "#<number>" if unresolved; "" = race-level
    team = models.CharField(max_length=80, blank=True, default="")
    type = models.CharField(max_length=24)
    source = models.CharField(max_length=40)  # track_status | race_control | track_status+race_control | results | pit_stops
    end_lap = models.PositiveSmallIntegerField(null=True, blank=True)  # neutralisations only
    mapping_version = models.CharField(max_length=16, blank=True, default="")  # DNF status mapping version
    detail = models.JSONField(default=dict)  # raw status string, stop duration + threshold, crosscheck notes
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_chaos_label_race"),
            models.Index(fields=["type", "year"], name="idx_chaos_label_type_year"),
        ]

    def __str__(self):
        return f"{self.year} R{self.round_number} {self.type} lap={self.lap} {self.driver}"


class FeatureSet(models.Model):
    """One Parquet file of numeric features for one scope (race / driver / lap_window)."""

    version = models.CharField(max_length=80)
    scope = models.CharField(max_length=12)
    path = models.CharField(max_length=500)
    columns = models.JSONField(default=list)
    row_count = models.PositiveIntegerField()
    meta = models.JSONField(default=dict)  # target columns, live-only columns, mapping version
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "scope"], name="uniq_chaos_featureset_version_scope")]


class ModelRun(models.Model):
    model = models.CharField(max_length=40)  # beta_binomial | kumo_tabular | ...
    size = models.CharField(max_length=16, blank=True, default="")
    race_key = models.CharField(max_length=32, blank=True, default="")  # "2024-05": the race predicted; one run per (model, race); "loso-2018-2025" for a backtest
    context_rows = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict)
    calibration = models.JSONField(default=dict)
    git_sha = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["model", "size", "race_key"], name="uniq_chaos_modelrun_model_size_race")]


class ChaosPrediction(models.Model):
    """probability = posterior/calibrated rate of the target per entity; p10/p90 = interval on that rate."""

    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    scope = models.CharField(max_length=12)  # race | driver | lap_window
    entity = models.CharField(max_length=16, blank=True, default="")  # "" race, driver code, or "w<index>"
    target = models.CharField(max_length=24)
    probability = models.FloatField()
    p10 = models.FloatField()
    p90 = models.FloatField()
    model_run = models.ForeignKey(ModelRun, on_delete=models.CASCADE, related_name="predictions")

    class Meta:
        indexes = [models.Index(fields=["year", "round_number", "scope"], name="idx_chaos_pred_race_scope")]
