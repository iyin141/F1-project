"""
Django signals for Phase 6: Race completion detection and proactive prefetching.

When a race result is created/updated, check if the race session has completed.
If complete, trigger prefetch of high-traffic endpoints to warm cache.
"""
from __future__ import annotations

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from api.models import RaceResultData
from api.services.seeding import prefetch_race_completion, detect_race_completion

logger = logging.getLogger(__name__)


@receiver(post_save, sender=RaceResultData)
def on_race_result_created(sender, instance, created, **kwargs):
    """
    Phase 6 Problem 21: Detect race completion and prefetch high-traffic endpoints.
    
    When a race result is created, check if the race session has completed.
    If so, dispatch prefetch tasks for results, incidents, weather to warm Redis.
    """
    if not created:
        # Only on initial creation, not updates
        return
    
    try:
        # Extract year and round from the result
        year = instance.year
        # Model field is `round_number`; use that to avoid AttributeError
        round_number = instance.round_number
        
        logger.debug(
            "[RaceCompletionSignal] Checking race completion year=%s round=%s",
            year, round_number,
        )
        
        # Check if race is complete
        if detect_race_completion(year, round_number):
            logger.info(
                "[RaceCompletionSignal] Race complete, prefetching endpoints year=%s round=%s",
                year, round_number,
            )
            
            # Dispatch prefetch tasks
            task_ids = prefetch_race_completion(year, round_number)
            
            logger.info(
                "[RaceCompletionSignal] Prefetch dispatched (%d tasks) year=%s round=%s",
                len(task_ids), year, round_number,
            )
        else:
            logger.debug(
                "[RaceCompletionSignal] Race not yet complete year=%s round=%s",
                year, round_number,
            )
    
    except Exception as exc:
        logger.warning(
            "[RaceCompletionSignal] Prefetch dispatch failed: %s", exc,
        )
