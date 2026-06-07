import os

worker_files = [
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier4_telemetry\populate_telemetry_overlay.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier4_telemetry\populate_telemetry.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_tyre_strategy.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_telemetry_summary.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_stint_analysis.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_sector_analysis.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_pace_analysis.py",
    r"c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\workers\tier3_medium\populate_laps.py",
]

for filepath in worker_files:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        new_content = content.replace("from api.views import _ensure_payload_meta_checklist", "from api.core import _ensure_payload_meta_checklist")
        
        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Updated {os.path.basename(filepath)}")

print("Done updating imports.")
