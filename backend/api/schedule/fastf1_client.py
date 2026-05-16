"""FastF1 HTTP client for schedule data."""
from __future__ import annotations

import logging
import pandas as pd

from api.session.runtime import fastf1

logger = logging.getLogger(__name__)


def fetch_season_schedule(year: int) -> list[dict]:
    """Fetch schedule from FastF1 and format into dictionary list."""
    try:
        schedule = fastf1.get_event_schedule(year)

        schedule_data = []
        for _, row in schedule.iterrows():
            if pd.isna(row['RoundNumber']) or row['RoundNumber'] == 0:
                continue
                
            race_info = {
                'round': int(row['RoundNumber']),
                'name': row['EventName'],
                'date': row['EventDate'].strftime('%Y-%m-%d') if pd.notna(row['EventDate']) else None,
                'location': row['Location'],
                'country': row['Country'],
                'event_format': row.get('EventFormat'),
                'session1': row.get('Session1'),
                'session1_date_utc': row['Session1DateUtc'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('Session1DateUtc')) else None,
                'session2': row.get('Session2'),
                'session2_date_utc': row['Session2DateUtc'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('Session2DateUtc')) else None,
                'session3': row.get('Session3'),
                'session3_date_utc': row['Session3DateUtc'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('Session3DateUtc')) else None,
                'session4': row.get('Session4'),
                'session4_date_utc': row['Session4DateUtc'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('Session4DateUtc')) else None,
                'session5': row.get('Session5'),
                'session5_date_utc': row['Session5DateUtc'].strftime('%Y-%m-%dT%H:%M:%SZ') if pd.notna(row.get('Session5DateUtc')) else None,
            }
            schedule_data.append(race_info)

        return schedule_data

    except Exception as e:
        logger.error("FastF1 schedule fetch failed for %s: %s", year, e)
        raise
