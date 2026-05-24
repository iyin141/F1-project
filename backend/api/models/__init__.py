"""
API models package — re-exports all models for Django discovery.

Usage: ``from api.models import SeasonSchedule, TaskRecord, ...``
"""
from api.models.races import (
    SeasonSchedule,
    RaceResultData,
    QualifyingResultData,
    PracticeResultData,
)
from api.models.analysis import DriverLapAnalysis, DriverTelemetry
from api.models.unified import SessionData
from api.models.standings import DriverStandings, ConstructorStandings, DriverCareer, DriverSeasonBreakdown
from api.models.queue import TaskRecord
from api.models.auth import APIKey
from api.models.drivers import F1Driver
from api.models.champions import F1Champion

__all__ = [
    "SeasonSchedule",
    "RaceResultData",
    "QualifyingResultData",
    "PracticeResultData",
    "DriverLapAnalysis",
    "DriverTelemetry",
    "SessionData",
    "DriverStandings",
    "ConstructorStandings",
    "DriverCareer",
    "DriverSeasonBreakdown",
    "TaskRecord",
    "APIKey",
    "F1Driver",
    "F1Champion",
]
