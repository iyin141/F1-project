"""
Central mapping of all F1 data endpoints to their FastF1 session.load() requirements.

This map defines what data each worker needs to load from FastF1, eliminating hardcoded
load flags scattered across worker implementations. Workers import this map and use it
to determine which flags to pass to session.load().

Key patterns:
- 'skip_session_load': True for endpoints that don't need FastF1 (standings, schedule, derived types)
- Load flags: laps, telemetry, weather, messages, pit_stops, incidents, pos_changes, drs, track_status, livedata
- Some endpoints need multiple flags (e.g., race_results needs laps=True, telemetry=False)
"""

ENDPOINT_LOAD_MAP = {
    # Standings & Schedule (no FastF1 load needed - read from Jolpica/cache)
    "driver_standings": {
        "skip_session_load": True,
        "source": "jolpica",
        "description": "Driver championship standings"
    },
    "constructor_standings": {
        "skip_session_load": True,
        "source": "jolpica",
        "description": "Constructor championship standings"
    },
    "season_schedule": {
        "skip_session_load": True,
        "source": "jolpica",
        "description": "Season race calendar and schedule"
    },

    # Race Results (laps for lap info)
    "race_results": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Final race results, finishing positions, gaps"
    },

    # Qualifying Results (laps for lap times)
    "qualifying_results": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Qualifying results and lap times"
    },

    # Practice Results (laps for lap times)
    "practice_results": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Practice session results and lap times"
    },

    # Lap Analysis (laps for detailed analysis)
    "laps": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Detailed lap analysis with sectors, compound, drivers"
    },

    # Lap Analysis Pagination (laps)
    "paginate_laps": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Paginated lap data"
    },

    # Position Analysis (pos_changes for position tracking, laps for context)
    "positions": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": True,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Position changes and overtakes"
    },

    # Position Pagination (pos_changes)
    "paginate_positions": {
        "laps": False,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": True,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Paginated position data"
    },

    # DRS Activations (drs)
    "drs": {
        "laps": False,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": True,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "DRS activation events and statistics"
    },

    # Incidents (messages for incident events)
    "incidents": {
        "laps": False,
        "telemetry": False,
        "weather": False,
        "messages": True,
        "pit_stops": False,
        "incidents": True,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Safety car, red flags, collisions"
    },

    # Pit Stops (messages for pit events)
    "pit_stops": {
        "laps": False,
        "telemetry": False,
        "weather": False,
        "messages": True,
        "pit_stops": True,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Pit stop timing, duration, compound"
    },

    # Track Status (messages for track status changes)
    "track_status": {
        "laps": False,
        "telemetry": False,
        "weather": False,
        "messages": True,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": True,
        "livedata": False,
        "skip_session_load": False,
        "description": "Track status timeline (green, yellow, red, VSC)"
    },

    # Weather (weather for weather data)
    "weather": {
        "laps": False,
        "telemetry": False,
        "weather": True,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Weather conditions throughout session"
    },

    # Telemetry (telemetry for driver telemetry data)
    "telemetry": {
        "laps": True,
        "telemetry": True,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Per-driver telemetry (speed, throttle, brake, steering)"
    },

    # Telemetry Pagination (telemetry)
    "paginate_telemetry": {
        "laps": True,
        "telemetry": True,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Paginated telemetry data"
    },

    # Derived Analysis Types (computed from laps, no additional load needed)
    "stint_analysis": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Stint analysis (pit strategies, compound changes)"
    },

    "pace_analysis": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Pace trends and performance analysis"
    },

    "sector_analysis": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Sector-by-sector performance breakdown"
    },

    "tyre_strategy": {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
        "pit_stops": False,
        "incidents": False,
        "pos_changes": False,
        "drs": False,
        "track_status": False,
        "livedata": False,
        "skip_session_load": False,
        "description": "Tyre strategy and compound analysis"
    },
}


def get_load_flags(data_type: str) -> dict:
    """
    Get FastF1 session.load() flags for a specific data type.
    
    Args:
        data_type: Key from ENDPOINT_LOAD_MAP (e.g., "laps", "weather")
    
    Returns:
        dict with keys: laps, telemetry, weather, messages, pit_stops, incidents, 
                        pos_changes, drs, track_status, livedata, skip_session_load
    
    Raises:
        KeyError: If data_type not found in ENDPOINT_LOAD_MAP
    """
    if data_type not in ENDPOINT_LOAD_MAP:
        raise KeyError(f"Unknown data_type: {data_type}. Available types: {list(ENDPOINT_LOAD_MAP.keys())}")
    
    return ENDPOINT_LOAD_MAP[data_type]


def should_skip_session_load(data_type: str) -> bool:
    """
    Check if a data type requires FastF1 session.load() or can be derived from cache/Jolpica.
    
    Args:
        data_type: Key from ENDPOINT_LOAD_MAP
    
    Returns:
        True if session.load() should be skipped, False otherwise
    """
    return get_load_flags(data_type).get("skip_session_load", False)


def get_session_load_kwargs(data_type: str) -> dict:
    """
    Get kwargs dict ready to pass to FastF1 session.load(**kwargs).
    
    Automatically excludes 'skip_session_load' and other non-load-flag keys.
    
    Args:
        data_type: Key from ENDPOINT_LOAD_MAP
    
    Returns:
        dict with only FastF1 load flags (laps, telemetry, weather, etc.)
    """
    flags = get_load_flags(data_type)
    load_flags = {
        k: v for k, v in flags.items()
        if k in ('laps', 'telemetry', 'weather', 'messages', 'pit_stops', 
                'incidents', 'pos_changes', 'drs', 'track_status', 'livedata')
    }
    return load_flags
