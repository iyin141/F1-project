"""Invalidate cached chaos responses when a ModelRun lands (new or refreshed)."""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .cache import bump_version
from .models import ModelRun


@receiver(post_save, sender=ModelRun)
def _model_run_saved(sender, **kwargs):
    transaction.on_commit(bump_version)  # after the predictions of the same atomic block are written
