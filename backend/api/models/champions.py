"""F1 Championship persistence model."""
from django.db import models


class F1Champion(models.Model):
    """
    All-time F1 World Champions, synced from Jolpica.
    One row per season.
    """
    year = models.IntegerField(unique=True, db_index=True)
    driver_id = models.CharField(max_length=100)  # max_verstappen
    driver_code = models.CharField(max_length=10, null=True, blank=True)  # VER
    driver_name = models.CharField(max_length=200)
    team = models.CharField(max_length=200, null=True, blank=True)
    points = models.FloatField(null=True, blank=True)
    wins = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year']
        verbose_name = 'F1 Champion'
        verbose_name_plural = 'F1 Champions'

    def __str__(self):
        return f"{self.year} — {self.driver_name} ({self.driver_code})"
