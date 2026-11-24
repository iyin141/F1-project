"""Invalidate cached chaos responses when a ModelRun lands (new or refreshed)."""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from api.trackmap.models import TrackGeometry

from .cache import bump_version
from .circuits import link_geometry
from .models import ModelRun


logger = logging.getLogger(__name__)


@receiver(post_save, sender=ModelRun)
def _model_run_saved(sender, **kwargs):
    transaction.on_commit(bump_version)  # after the predictions of the same atomic block are written


@receiver(post_save, sender=TrackGeometry)
def _geometry_built(sender, instance, created, **kwargs):
    """Link the new geometry's circuit_key (and length/corners) to its CircuitProfile. A signal rather than an edit to
    trackmap (owned by another branch): the geometry row already says which race built it, and the cache pointer trackmap
    also writes only appears AFTER this save, so it cannot be used here. Never lets a linking error break the track-map build."""
    if not created:
        return

    def run():
        try:
            link_geometry(instance)
        except Exception:  # noqa: BLE001
            logger.exception("[chaos] linking circuit for track geometry %s failed", instance.pk)

    transaction.on_commit(run)
