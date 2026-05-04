"""
F1 Schedule Service
Fetches season schedule data using FastF1 library.
"""
import pandas as pd
from datetime import datetime

from .fastf1_runtime import fastf1
from .persistence import get_persisted_race_by_round, get_persisted_season_schedule


def get_season_schedule(year=None):
    """
    Fetch the F1 season schedule for a given year.

    Args:
        year (int): The season year. Defaults to current year.

    Returns:
        list: List of race dictionaries with schedule information
    """
    if year is None:
        year = datetime.now().year

    persisted_schedule = get_persisted_season_schedule(year)

    try:
        # Fetch the schedule using FastF1
        schedule = fastf1.get_event_schedule(year)

        # Extract relevant columns and convert to list of dicts
        schedule_data = []
        for _, row in schedule.iterrows():
            # Skip non-race events (Pre-Season Testing, etc)
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

        if persisted_schedule:
            persisted_by_round = {race["round"]: race for race in persisted_schedule}
            schedule_data = [persisted_by_round.get(race["round"], race) for race in schedule_data]

        return schedule_data

    except Exception as e:
        if persisted_schedule:
            return persisted_schedule
        raise Exception(f"Error fetching F1 schedule: {str(e)}")


def get_race_by_round(year=None, round_number=None):
    """
    Get a specific race by round number.

    Args:
        year (int): The season year
        round_number (int): The round number

    Returns:
        dict: Race information
    """
    if year is None:
        year = datetime.now().year

    persisted_race = get_persisted_race_by_round(year, round_number)
    if persisted_race is not None:
        return persisted_race

    schedule = get_season_schedule(year)

    for race in schedule:
        if race['round'] == round_number:
            return race

    return None
