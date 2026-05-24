"""
F1Driver model — canonical driver records sourced from Jolpica.

Stores driver metadata indexed for instant search + name resolution.
Updated via DriverSyncService; separate from standings/career models (no FK).
"""
from django.db import models


class F1Driver(models.Model):
    """
    Canonical F1 driver record sourced from Jolpica.

    Fields:
      - driver_id: Unique Jolpica identifier (e.g., "max_verstappen")
      - code: 3-letter driver code (e.g., "VER", "HAM")
      - number: Car permanent number (e.g., "1")
      - given_name: First name
      - family_name: Last name (indexed for search)
      - nationality: Country of origin
      - dob: Date of birth (e.g., "1997-03-31")
      - seasons: JSONField list of years driver competed [2015, 2016, ...]

    Indexes:
      - (family_name, given_name): Compound search by name
      - (code): Lookup by 3-letter code
    """

    driver_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique Jolpica identifier (e.g., 'max_verstappen')"
    )
    code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        db_index=True,
        help_text="3-letter driver code (e.g., 'VER', 'HAM')"
    )
    number = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Car permanent number (e.g., '1')"
    )
    given_name = models.CharField(
        max_length=100,
        help_text="First name"
    )
    family_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Last name (indexed for search)"
    )
    nationality = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Country of origin"
    )
    dob = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Date of birth (YYYY-MM-DD)"
    )
    seasons = models.JSONField(
        default=list,
        help_text="List of years driver competed [2015, 2016, ...]"
    )

    class Meta:
        ordering = ['family_name', 'given_name']
        indexes = [
            models.Index(fields=['family_name', 'given_name']),
            models.Index(fields=['code']),
        ]
        verbose_name = "F1 Driver"
        verbose_name_plural = "F1 Drivers"

    def __str__(self):
        return f"{self.given_name} {self.family_name} ({self.driver_id})"

    @property
    def full_name(self):
        """Return formatted full name."""
        return f"{self.given_name} {self.family_name}".strip()
