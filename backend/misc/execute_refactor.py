import os
import ast
from pathlib import Path
import re

BASE_DIR = Path(r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend")
API_DIR = BASE_DIR / "api"

def get_class_source(filepath, class_name):
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    
    # We can use regex to extract class blocks from the monolithic file, assuming standard formatting
    # Regex matches 'class {class_name}' and captures until the next 'class ' at col 0, or end of file
    pattern = rf"^(class {class_name}\b.*?(?=\nclass |\Z))"
    match = re.search(pattern, source, flags=re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip() + "\n\n"
    return ""

def generate_serializers():
    MONO_SERIALIZERS = API_DIR / "serializers.py"
    
    # Mappings
    domains = {
        "constructors": ["ConstructorSerializer", "ConstructorStandingsResponseSerializer"],
        "drivers": [
            "DriverStandingSerializer", "DriverStandingsResponseSerializer",
            "DriverCareerSeasonSerializer", "DriverCareerTotalsSerializer",
            "DriverCareerResponseSerializer", "DriverRoundResultSerializer",
            "DriverSeasonResponseSerializer", "DriverSearchResultSerializer",
            "DriverSearchResponseSerializer", "DriverSyncResponseSerializer",
            "DriverListItemSerializer", "DriverListResponseSerializer",
            "DriverSearchMatchesSerializer", "DriverSearchByNameResultSerializer",
            "DriverSearchByNameResponseSerializer"
        ],
        "results": [
            "RaceResultSerializer", "RaceResultsSerializer",
            "QualifyingResultSerializer", "PracticeResultSerializer"
        ],
        "schedule": ["RaceSerializer"],
        "session": [
            "LapAnalysisRowSerializer", "LapAnalysisMetaSerializer", "LapAnalysisFiltersSerializer",
            "LapAnalysisResponseSerializer", "StintAnalysisRowSerializer", "StintAnalysisResponseSerializer",
            "LapAnalysisSerializer", "StintAnalysisSerializer", "DriverTelemetrySerializer",
            "PaceAnalysisRowSerializer", "PaceAnalysisResponseSerializer", "TelemetryAnalysisPointSerializer",
            "TelemetryAnalysisFiltersSerializer", "TelemetryAnalysisResponseSerializer", "TelemetryOverlayTraceSerializer",
            "TelemetryOverlayFiltersSerializer", "TelemetryOverlayResponseSerializer", "TelemetrySummaryFiltersSerializer",
            "TelemetrySummaryPayloadSerializer", "TelemetrySummaryResponseSerializer", "TyreStrategyRowSerializer",
            "TyreStrategyResponseSerializer", "SectorAnalysisRowSerializer", "SectorAnalysisResponseSerializer",
            "UnifiedMetaSerializer", "UnifiedFiltersSerializer", "UnifiedBaseResponseSerializer",
            "WeatherRowSerializer", "WeatherResponseSerializer", "PitStopRowSerializer", "PitStopResponseSerializer",
            "IncidentRowSerializer", "IncidentResponseSerializer", "PositionChangeRowSerializer",
            "PositionResponseSerializer", "DRSRowSerializer", "DRSResponseSerializer", "TrackStatusRowSerializer",
            "TrackStatusResponseSerializer", "TyreDegradationRowSerializer", "TyreDegradationResponseSerializer"
        ]
    }

    base_imports = 'from rest_framework import serializers\nfrom api.common.serializers import ReadinessSerializer\n\n'

    for domain, classes in domains.items():
        domain_dir = API_DIR / domain
        domain_dir.mkdir(exist_ok=True)
        out_path = domain_dir / "serializers.py"
        
        content = base_imports
        for cls in classes:
            src = get_class_source(MONO_SERIALIZERS, cls)
            if src:
                content += src
        
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Generated {out_path}")

def generate_views():
    # Similar extraction for views from driver_views.py, driver_views_new.py, views.py
    # Actually, it's easier to just move the files and rewrite imports.
    # Driver views:
    driver_views_path = API_DIR / "drivers" / "views.py"
    try:
        with open(API_DIR / "driver_views.py", "r", encoding="utf-8") as f1:
            dv1 = f1.read()
    except FileNotFoundError:
        dv1 = ""
    try:
        with open(API_DIR / "driver_views_new.py", "r", encoding="utf-8") as f2:
            dv2 = f2.read()
    except FileNotFoundError:
        dv2 = ""
        
    combined = dv1 + "\n\n" + dv2
    # Ensure driver domain has views.py
    with open(driver_views_path, "w", encoding="utf-8") as f:
        f.write(combined)
    print(f"Generated {driver_views_path}")
    
    # We will leave views.py extraction for manual or a later script step since it requires extracting logic
    # Wait, the monolithic views.py has `ConstructorStandingsAPIView`, `AnalysisLapsAPIView`, etc.

if __name__ == "__main__":
    generate_serializers()
    generate_views()
