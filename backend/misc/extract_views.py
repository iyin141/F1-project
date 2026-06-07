import os
import re
from pathlib import Path

BASE_DIR = Path(r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend")
VIEWS_FILE = BASE_DIR / "api" / "views.py"

def extract_class(content, class_name):
    # Regex to find class and everything indented below it, until next class or function at column 0
    pattern = rf"^(class {class_name}\b.*?(?=\nclass |\ndef |\Z))"
    match = re.search(pattern, content, flags=re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip() + "\n\n"
    return ""

def main():
    with open(VIEWS_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 1. Extract Constructor Views
    constructor_views = ["ConstructorStandingsAPIView"]
    constructors_content = "import logging\nfrom rest_framework.views import APIView\nfrom rest_framework.response import Response\nfrom drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter\nfrom drf_spectacular.types import OpenApiTypes\nfrom api.common.readiness import build_readiness\nfrom api.common.response import build_error_payload\nfrom api.services.nonblocking import handle_data_request\nfrom api.tasks import populate_constructor_standings\nfrom api.constructors.serializers import ConstructorStandingsResponseSerializer\nfrom api.services.persistence import get_persisted_constructor_standings\n\nlogger = logging.getLogger(__name__)\n\n"
    for cls in constructor_views:
        constructors_content += extract_class(content, cls)
        
    out_constructors = BASE_DIR / "api" / "constructors" / "views.py"
    with open(out_constructors, "w", encoding="utf-8") as f:
        f.write(constructors_content)
        
    # 2. Extract Session Views
    session_views = [
        "AnalysisLapsAPIView", "AnalysisStintsAPIView", "AnalysisPaceAPIView",
        "AnalysisTyreStrategyAPIView", "AnalysisSectorAPIView", "AnalysisTelemetryAPIView",
        "AnalysisTelemetryOverlayAPIView", "AnalysisTelemetrySummaryAPIView",
        "UnifiedFullSessionAPIView", "UnifiedWeatherAPIView", "UnifiedPitStopsAPIView",
        "UnifiedIncidentsAPIView", "UnifiedPositionsAPIView", "UnifiedDRSAPIView",
        "UnifiedTrackStatusAPIView"
    ]
    
    session_content = "import logging\nimport os\nimport json\nfrom django.core.cache import cache\nfrom rest_framework.views import APIView\nfrom rest_framework.response import Response\nfrom drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter\nfrom drf_spectacular.types import OpenApiTypes\nfrom api.common.readiness import build_readiness\nfrom api.common.response import build_error_payload\nfrom api.services.nonblocking import handle_data_request\n"
    session_content += "from api.session.serializers import *\n"
    session_content += "from api.services.persistence import *\n"
    session_content += "from api.tasks import *\n"
    session_content += "from api.services.unified_service import EXTRACTORS_MAP\n"
    session_content += "from api.services import streaming\nfrom api.queue.manager import TaskManager\n"
    session_content += "\nlogger = logging.getLogger(__name__)\n\n"
    
    # We should also copy helper functions if any exist, but we can just use wildcard imports or manually check.
    # We will just copy the _build_standard_response helper if it's there.
    helper_pattern = r"^(def _build_standard_response.*?)(?=\nclass |\ndef |\Z)"
    h_match = re.search(helper_pattern, content, flags=re.MULTILINE | re.DOTALL)
    if h_match:
        session_content += h_match.group(1).strip() + "\n\n"
        
    for cls in session_views:
        session_content += extract_class(content, cls)
        
    out_session = BASE_DIR / "api" / "session" / "views.py"
    out_session.parent.mkdir(exist_ok=True)
    with open(out_session, "w", encoding="utf-8") as f:
        f.write(session_content)

if __name__ == "__main__":
    main()
