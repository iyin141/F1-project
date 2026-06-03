import sys
import importlib
import traceback

migrations_dir = 'api.migrations'
migration_files = [
    '0001_initial',
    '0002_sectoraggregate',
    '0003_drop_django_builtin_auth_tables',
    '0004_driverseasonsummary',
    '0005_race_event_format_race_session1_and_more',
    '0006_raceresult_time',
    '0007_remove_raceresult_time_constructorstandings_and_more',
    '0008_remove_drivermetric_idx_metric_race_consistency_and_more',
    '0009_taskrecord',
    '0010_drop_background_task_tables',
    '0011_alter_taskrecord_task_key',
    '0012_add_driver_career_season_breakdown',
    '0013_telemetry_per_driver_session',
    '0014_remove_constructorstandings_idx_constructor_standings_year_and_more',
    '0015_add_missing_indexes',
    '0016_apikey',
    '0017_apikey_tier_rename',
    '0018_f1driver',
    '0019_f1champion',
    '0020_taskrecord_meta',
    '0021_taskrecord_drop_celery_task_id_add_started_at',
    '0022_remove_taskrecord_meta_drsdata_incidentdata_and_more',
    '0023_remove_sessiondata_idx_sd_year_round_and_more',
]

failed = []
for mig_file in migration_files:
    try:
        module_name = f'{migrations_dir}.{mig_file}'
        mod = importlib.import_module(module_name)
        print(f"OK {mig_file}")
    except Exception as e:
        print(f"FAIL {mig_file}: {e}")
        failed.append((mig_file, e))

if failed:
    print(f"\n{len(failed)} migration(s) failed to import:")
    for mig_file, err in failed:
        print(f"\n{mig_file}:")
        traceback.print_exception(type(err), err, err.__traceback__)
else:
    print(f"\nAll {len(migration_files)} migrations imported successfully")
