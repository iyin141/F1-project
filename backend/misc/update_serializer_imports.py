import os
from pathlib import Path
import re

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

# Invert mapping to find which domain a class belongs to
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
                    content = f.read()
                
                new_content = content
                
from api.serializers import X, Y`
                # A robust way is to just replace `api.serializers` with the domain one if we know the domain.
                # However, an import line might have multiple classes from different domains!
from api.drivers.serializers import DriverStandingSerializer
from api.serializers import RaceSerializer`
from api.serializers import (.*)'
                # and replacing the line with the properly grouped ones.
                
                def import_replacer(match):
                    import_str = match.group(1)
                    # It might span multiple lines if there are parens, but let's assume it's one line for simplicity.
                    # Or we just iterate over all keys.
                    return match.group(0) # Not doing it this way
                
from api.serializers import s `from api.serializers
                # we'll use a regex to capture the whole import block.
                import_pattern = re.compile(r"^from api\.serializers import\s+(?:\((.*?)\)|(.*))", re.MULTILINE | re.DOTALL)
                
                matches = import_pattern.finditer(new_content)
                for m in reversed(list(matches)):
                    full_match = m.group(0)
                    classes_str = m.group(1) if m.group(1) else m.group(2)
                    classes = [c.strip() for c in classes_str.replace('\n', '').split(',') if c.strip()]
                    
                    domain_to_imported_classes = {}
                    for cls in classes:
                        # cls might be `RaceSerializer as RS`
                        base_cls = cls.split(" as ")[0].strip()
                        domain = class_to_domain.get(base_cls)
                        if domain:
                            domain_to_imported_classes.setdefault(domain, []).append(cls)
                        else:
                            # Fallback if we missed a class
                            domain_to_imported_classes.setdefault("serializers_fallback", []).append(cls)
                    
                    replacement_lines = []
                    for domain, imported_classes in domain_to_imported_classes.items():
                        if domain == "serializers_fallback":
from api.serializers import {', '.join(
                        else:
                            replacement_lines.append(f"from api.{domain}.serializers import {', '.join(imported_classes)}")
                    
                    replacement_text = "\n".join(replacement_lines)
                    new_content = new_content[:m.start()] + replacement_text + new_content[m.end():]
                
                # Also replace direct usages: `import api.serializers` -> this is harder.
                # We'll just replace `api.serializers.X` with `api.domain.serializers.X`
                for cls, domain in class_to_domain.items():
                    new_content = new_content.replace(f"api.serializers.{cls}", f"api.{domain}.serializers.{cls}")
                    
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"Updated serializer imports in {path}")
            except Exception as e:
                print(f"Error processing {path}: {e}")
