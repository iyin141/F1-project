from celery import shared_task
import logging

from api.services.task_manager import TaskManager

logger = logging.getLogger(__name__)


@shared_task(bind=False, max_retries=0, queue="tier1_instant")
def check_for_completed_sessions():
    """
    Beat task: detect race sessions that ended in the last 15 minutes and fire
    prefetch_race_weekend for each.

    Queries SeasonSchedule for the current year and checks each round's
    session5_date_utc (the main race session).  A 16-minute look-back window
    ensures overlap with the previous run so no session is missed on edge-case
    timing.

    Runs every 15 minutes via app.conf.beat_schedule in celery.py.
    Phase 6.
    """
    from datetime import datetime, timedelta
    from django.utils.timezone import now as django_now
    from api.models import SeasonSchedule

    logger.info("event=celery_start task=check_for_completed_sessions")

    now = django_now()
    window_start = now - timedelta(minutes=16)

    try:
        current_year = now.year
        schedule_record = SeasonSchedule.objects.filter(year=current_year).first()

        if not schedule_record:
            logger.info("event=no_schedule task=check_for_completed_sessions year=%s", current_year)
            return

        races = schedule_record.payload.get("races", [])
        fired = 0

        for race in races:
            session5_date = race.get("session5_date_utc")
            if not session5_date:
                continue

            try:
                session_dt = datetime.fromisoformat(session5_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if window_start <= session_dt <= now:
                round_number = race.get("round")
                if not round_number:
                    continue

                task_key = f"prefetch:{int(current_year)}:{int(round_number)}"
                logger.info(
                    "event=session_completed year=%s round=%s session_dt=%s",
                    current_year, round_number, session5_date,
                )
                TaskManager.enqueue_if_needed(
                    task_key,
                    # import local reference to avoid circular imports at module load
                    __import__("api.tasks", fromlist=["prefetch_race_weekend"]).prefetch_race_weekend,
                    int(current_year),
                    int(round_number),
                )
                fired += 1

        logger.info(
            "event=celery_success task=check_for_completed_sessions fired=%d year=%s",
            fired, current_year,
        )
    except Exception as exc:
        logger.exception("event=celery_failed task=check_for_completed_sessions error=%s", exc)
        raise
