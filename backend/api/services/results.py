"""
F1 Results Service
Fetches race results (qualifying and race) data using FastF1 library.
"""
import pandas as pd
from datetime import datetime

from .fastf1_runtime import fastf1


def get_race_results(year=None, round_number=None):
    """
    Fetch qualifying and race results for a specific round.

    Args:
        year (int): The season year. Defaults to current year.
        round_number (int): The round number (1-24, depending on season).

    Returns:
        dict: Contains 'qualifying' and 'race' keys, each with a list of result dictionaries
    """
    if year is None:
        year = datetime.now().year

    if round_number is None:
        raise ValueError("round_number parameter is required")

    try:
        # Get the session object for the race
        session = fastf1.get_session(year, round_number, 'R')
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        results_dict = {
            'qualifying': get_qualifying_results(year, round_number),
            'race': get_race_session_results(session),
        }

        return results_dict

    except Exception as e:
        raise Exception(f"Error fetching F1 race results for {year} Round {round_number}: {str(e)}")


def get_practice_session_results(year, round_number, session_name):
    """
    Get fastest-lap leaderboard for a practice session.

    Args:
        year (int): The season year.
        round_number (int): The round number.
        session_name (str): Practice session name (FP1, FP2, FP3).

    Returns:
        list: Fastest lap result dictionaries for the session.
    """
    normalized_session = str(session_name).upper()
    allowed_sessions = {"FP1", "FP2", "FP3"}
    if normalized_session not in allowed_sessions:
        raise ValueError("session_name must be one of FP1, FP2, FP3")

    try:
        session = fastf1.get_session(year, round_number, normalized_session)
        session.load(telemetry=False, weather=False, messages=False)

        laps = session.laps.copy()
        laps = laps[laps["LapTime"].notna()]

        if laps.empty:
            raise Exception(f"No lap data available for {normalized_session}")

        fastest_laps = laps.loc[laps.groupby("Driver")["LapTime"].idxmin()].copy()
        fastest_laps = fastest_laps.sort_values("LapTime")

        practice_data = []
        for position, (_, row) in enumerate(fastest_laps.iterrows(), start=1):
            practice_data.append(
                {
                    "position": position,
                    "driver_code": row.get("Driver", "Unknown"),
                    "team": row.get("Team", "Unknown"),
                    "lap_time": str(row.get("LapTime")) if pd.notna(row.get("LapTime")) else None,
                    "lap_number": int(row.get("LapNumber")) if pd.notna(row.get("LapNumber")) else None,
                }
            )

        return practice_data

    except Exception as e:
        raise Exception(
            f"Error fetching practice results for {year} Round {round_number} {normalized_session}: {str(e)}"
        )


def get_qualifying_results(year, round_number):
    """
    Get qualifying session results for a specific round.

    Args:
        year (int): The season year.
        round_number (int): The round number.

    Returns:
        list: List of qualifying result dictionaries
    """
    try:
        session = fastf1.get_session(year, round_number, 'Q')
        session.load(laps=False, telemetry=False, weather=False, messages=False)

        qualifying_data = []
        results = session.results

        for _, row in results.iterrows():
            # Only include drivers who actually set qualifying times
            if pd.notna(row.get('Q1', None)):
                qualifying_info = {
                    'position': int(row['Position']) if pd.notna(row.get('Position', None)) else None,
                    'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                    'driver_name': row.get('FullName', 'Unknown'),
                    'team': row.get('TeamName', 'Unknown'),
                    'q1_time': str(row['Q1']) if pd.notna(row.get('Q1', None)) else None,
                    'q2_time': str(row['Q2']) if pd.notna(row.get('Q2', None)) else None,
                    'q3_time': str(row['Q3']) if pd.notna(row.get('Q3', None)) else None,
                }
                qualifying_data.append(qualifying_info)

        return qualifying_data

    except Exception as e:
        raise Exception(f"Error fetching qualifying results: {str(e)}")


def get_race_session_results(session):
    """
    Get race session results from a loaded session object.

    Args:
        session: A FastF1 session object (already loaded).

    Returns:
        list: List of race result dictionaries
    """
    try:
        race_data = []
        results = session.results

        for _, row in results.iterrows():
            race_info = {
                'position': int(row['Position']) if pd.notna(row.get('Position', None)) else None,
                'driver_number': int(row['DriverNumber']) if pd.notna(row.get('DriverNumber', None)) else None,
                'driver_name': row.get('FullName', 'Unknown'),
                'team': row.get('TeamName', 'Unknown'),
                'points': int(row['Points']) if pd.notna(row.get('Points', None)) else 0,
                'status': row.get('Status', 'Unknown'),
                'grid_position': int(row['GridPosition']) if pd.notna(row.get('GridPosition', None)) else None,
                'laps': int(row['Laps']) if pd.notna(row.get('Laps', None)) else 0,
            }
            race_data.append(race_info)

        return race_data

    except Exception as e:
        raise Exception(f"Error processing race results: {str(e)}")
