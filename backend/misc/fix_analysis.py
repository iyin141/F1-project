import re

file_path = r'c:\Users\iyino\Videos\F1-project\f1-project-backend\backend\api\services\analysis.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update imports
content = content.replace(
    'from api.tasks import populate_telemetry, populate_driver_telemetry, populate_race_results',
    'from api.tasks import populate_telemetry, populate_session_telemetry, populate_race_results'
)

# 2. Update get_telemetry_snapshot
target_1 = """                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver}",
                        task_fn=populate_driver_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                        driver_code=normalized_driver,
                    )"""
replacement_1 = """                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry_session_cache:{int(year)}:{int(round_number)}:{normalized_session}",
                        task_fn=populate_session_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                    )"""
content = content.replace(target_1, replacement_1)

# 3. Update get_telemetry_overlay
target_2 = """        # Enqueue per-driver independently — VER and LEC tasks never block each other
        if normalized_session == "R":
            _session_end = getattr(telemetry_session, "date", None)
            if _session_end is not None:
                if getattr(_session_end, "tzinfo", None) is None:
                    _session_end = make_aware(_session_end)
                if _session_end < timezone.now() and int(year) >= _TELEMETRY_MIN_YEAR:
                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver_a}",
                        task_fn=populate_driver_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                        driver_code=normalized_driver_a,
                    )
                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver_b}",
                        task_fn=populate_driver_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                        driver_code=normalized_driver_b,
                    )"""
replacement_2 = """        # Enqueue for the entire session
        if normalized_session == "R":
            _session_end = getattr(telemetry_session, "date", None)
            if _session_end is not None:
                if getattr(_session_end, "tzinfo", None) is None:
                    _session_end = make_aware(_session_end)
                if _session_end < timezone.now() and int(year) >= _TELEMETRY_MIN_YEAR:
                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry_session_cache:{int(year)}:{int(round_number)}:{normalized_session}",
                        task_fn=populate_session_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                    )"""
content = content.replace(target_2, replacement_2)

# 4. Update get_telemetry_summary
target_3 = """                    TaskManager.enqueue_if_needed(
                        task_key=f"telemetry:{int(year)}:{int(round_number)}:{normalized_session}:{normalized_driver}",
                        task_fn=populate_driver_telemetry,
                        year=int(year),
                        round_number=int(round_number),
                        session_type=normalized_session,
                        driver_code=normalized_driver,
                    )"""
# This target_3 is exactly the same as target_1, so target_1 replacement will actually fix both!
# Let's verify:
if target_1 not in content:
    print("WARNING: target_1 not found, maybe already replaced?")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated analysis.py successfully")
