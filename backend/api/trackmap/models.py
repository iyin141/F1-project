from django.db import models


class TrackGeometry(models.Model):
    """Downsampled circuit outline built once per layout from a pole lap.

    ``points`` is columnar: {"x": [...], "y": [...], "z": [...], "distance": [...]}.
    x/y/z are FastF1 position units (1/10 m); distance is metres from the start line.
    ``year`` is the season the geometry was first built from.
    """

    circuit_key = models.IntegerField()  # MultiViewer circuit key (session_info Meeting.Circuit.Key)
    year = models.PositiveSmallIntegerField()
    layout_hash = models.CharField(max_length=64)
    points = models.JSONField()
    corners = models.JSONField(default=list)  # [{number, letter, angle, distance, x, y}]
    mini_sectors = models.JSONField(default=dict)  # {"distance": {...}, "corners": {...}}
    drs_zones = models.JSONField(default=list)  # [{start_m, end_m}]; empty when the era has no DRS
    source = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["circuit_key", "layout_hash"], name="uniq_trackgeometry_circuit_layout"),
        ]
        indexes = [models.Index(fields=["circuit_key", "year"], name="idx_trackgeom_circuit_year")]

    def __str__(self):
        return f"TrackGeometry(circuit={self.circuit_key}, {self.layout_hash[:8]})"
