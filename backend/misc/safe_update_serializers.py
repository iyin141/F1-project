import os
from pathlib import Path

BASE_DIR = Path(r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend")

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

class_to_domain = {}
for domain, classes in domains.items():
    for cls in classes:
        class_to_domain[cls] = domain

for root, dirs, files in os.walk(BASE_DIR):
    if "venv" in root or ".pytest_cache" in root or "__pycache__" in root:
        continue
    for file in files:
        if file.endswith(".py"):
            path = Path(root) / file
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                changed = False
                for i, line in enumerate(lines):
                    from api.serializers import " in line:
                        from api.serializers import s like `from api.serializers
                        parts = line.split("import")[1].strip()
                        classes = [c.strip() for c in parts.split(",")]
                        
                        domain_groups = {}
                        for c in classes:
                            base_c = c.split(" as ")[0].strip()
                            d = class_to_domain.get(base_c, "serializers")
                            domain_groups.setdefault(d, []).append(c)
                        
                        whitespace = line[:len(line) - len(line.lstrip())]
                        new_lines = []
                        for d, grp in domain_groups.items():
                            if d == "serializers":
                                from api.serializers import {', '.join(grp)}\n")
                            else:
                                new_lines.append(f"{whitespace}from api.{d}.serializers import {', '.join(grp)}\n")
                        
                        lines[i] = "".join(new_lines)
                        changed = True
                    elif "api.serializers." in line:
                        # Direct usage replace
                        for cls, d in class_to_domain.items():
                            if f"api.serializers.{cls}" in line:
                                lines[i] = line.replace(f"api.serializers.{cls}", f"api.{d}.serializers.{cls}")
                                changed = True
                
                if changed:
                    with open(path, "w", encoding="utf-8") as f:
                        f.writelines(lines)
                    print(f"Updated {path}")
            except Exception as e:
                pass
