from django.db import models
from django.db.models import Q


class SessionData(models.Model):
    year = models.PositiveSmallIntegerField()
    round_number = models.PositiveSmallIntegerField()
    session = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "api"
        db_table = "session_data"
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session"],
                name="uniq_session_data_year_round_session",
            ),
            models.CheckConstraint(condition=Q(year__gte=1950), name="session_data_year_gte_1950"),
            models.CheckConstraint(condition=Q(round_number__gte=1), name="session_data_round_gte_1"),
        ]
        indexes = [
            models.Index(fields=["year", "round_number"], name="idx_sd_year_round"),
        ]

    def __str__(self):
        return f"SessionData({self.year}, R{self.round_number}, {self.session})"
