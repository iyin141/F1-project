"""
Django management command: Seed historical F1 race data.
Acts as a coordinator: fetches schedule, queues tasks for one round,
waits for them to complete (polling TaskRecord), and then moves to the next.
"""
import logging
import time
import os
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils import timezone
from api.models import SeasonSchedule, TaskRecord
from api.queue.manager import TaskManager
from api.tasks import populate_race_results

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Iteratively seed historical F1 race data round-by-round."

    def add_arguments(self, parser):
        parser.add_argument('--year-range', type=str, help='Year range to seed (e.g., 2018-2025)')
        parser.add_argument('--years', type=str, help='Comma-separated years (e.g., 2024,2023)')
        parser.add_argument('--rounds', type=str, help='Comma-separated rounds to seed (e.g., 1,5,10)')
        parser.add_argument('--poll-interval', type=int, default=5, help='Seconds between completion checks (default: 5)')
        parser.add_argument('--round-timeout', type=int, default=180, help='Max seconds to wait per round (default: 180)')

    def handle(self, *args, **options):
        years = self._parse_years(options)
        if not years:
            raise CommandError("Please specify --year-range or --years")

        target_rounds = self._parse_rounds(options)
        poll_interval = options['poll_interval']
        round_timeout = options['round_timeout']

        self.stdout.write(self.style.SUCCESS(f"Starting sequential seeding for years: {years}"))
        if target_rounds:
            self.stdout.write(self.style.SUCCESS(f"Targeting specific rounds: {target_rounds}"))

        total_rounds_completed = 0
        total_rounds_failed = 0
        total_sessions_processed = 0
        failed_rounds_list = []
        
        start_time_global = time.time()

        for year in years:
            self.stdout.write(f"\n[{year}] Fetching schedule...")
            call_command('populate_schedule', year=year)
            schedule_obj = SeasonSchedule.objects.filter(year=year).first()
            
            if not schedule_obj or not schedule_obj.payload.get('races'):
                self.stdout.write(self.style.ERROR(f"[{year}] Failed to load schedule. Skipping."))
                continue

            races = schedule_obj.payload.get('races', [])
            
            for race in races:
                round_number = race.get('round') or race.get('round_number') or race.get('roundNumber')
                if not round_number:
                    continue
                    
                if target_rounds and int(round_number) not in target_rounds:
                    continue

                event_format = (race.get('event_format') or 'conventional').lower()
                is_sprint = 'sprint' in event_format and event_format != 'conventional'

                sessions_to_dispatch = []
                sessions_to_dispatch.append(('practice_results', 'FP1'))
                sessions_to_dispatch.append(('practice_results', 'FP2'))
                if not is_sprint:
                    sessions_to_dispatch.append(('practice_results', 'FP3'))
                
                if is_sprint:
                    sessions_to_dispatch.append(('sprint_results', 'S'))
                    if year >= 2024:
                        sessions_to_dispatch.append(('sprint_shootout', 'SQ'))
                        
                sessions_to_dispatch.append(('qualifying', 'Q'))
                sessions_to_dispatch.append(('race_results', 'R'))

                task_keys = []
                for prefix, session_type in sessions_to_dispatch:
                    if prefix == 'practice_results':
                        task_key = f"{prefix}:{year}:{round_number}:{session_type}"
                    else:
                        task_key = f"{prefix}:{year}:{round_number}"
                    
                    # Dispatch
                    TaskManager.enqueue_if_needed(
                        task_key,
                        populate_race_results,
                        year,
                        round_number,
                        session_type
                    )
                    task_keys.append(task_key)
                
                total_sessions_processed += len(task_keys)
                self.stdout.write(f"[{year} Round {round_number}] Dispatched {len(task_keys)} sessions. Waiting...")

                # Polling loop
                start_time_round = time.time()
                round_failed = False
                
                while True:
                    elapsed = time.time() - start_time_round
                    if elapsed > round_timeout:
                        self.stdout.write(self.style.ERROR(f"[{year} Round {round_number}] TIMEOUT after {int(elapsed)}s"))
                        round_failed = True
                        break
                        
                    # Check statuses
                    records = TaskRecord.objects.filter(task_key__in=task_keys)
                    status_counts = {"complete": 0, "failed": 0, "running": 0, "pending": 0}
                    for r in records:
                        status_counts[r.status] = status_counts.get(r.status, 0) + 1
                        
                    # If not all records exist yet, count missing as pending
                    missing = len(task_keys) - len(records)
                    status_counts["pending"] += missing

                    if status_counts["failed"] > 0:
                        self.stdout.write(self.style.ERROR(f"[{year} Round {round_number}] FAILED ({status_counts['failed']} tasks failed)"))
                        round_failed = True
                        break
                        
                    if status_counts["complete"] == len(task_keys):
                        self.stdout.write(self.style.SUCCESS(f"[{year} Round {round_number}] COMPLETE in {int(elapsed)}s"))
                        break
                        
                    # Still running/pending
                    time.sleep(poll_interval)
                
                if round_failed:
                    total_rounds_failed += 1
                    failed_rounds_list.append(f"{year}-R{round_number}")
                else:
                    total_rounds_completed += 1
                    
                # Write log every 5 rounds
                if (total_rounds_completed + total_rounds_failed) % 5 == 0:
                    self._write_log(total_rounds_completed, total_rounds_failed, total_sessions_processed, start_time_global, failed_rounds_list)

            # Write log at end of year
            self._write_log(total_rounds_completed, total_rounds_failed, total_sessions_processed, start_time_global, failed_rounds_list)

        self.stdout.write(self.style.SUCCESS("\nSeeding Complete!"))
        self.stdout.write(f"Total Rounds Completed: {total_rounds_completed}")
        self.stdout.write(f"Total Rounds Failed: {total_rounds_failed}")
        if failed_rounds_list:
            self.stdout.write(self.style.WARNING(f"Failed Rounds: {', '.join(failed_rounds_list)}"))

    def _parse_years(self, options):
        if options['years']:
            return [int(y.strip()) for y in options['years'].split(',')]
        if options['year_range']:
            start, end = options['year_range'].split('-')
            start, end = int(start.strip()), int(end.strip())
            return list(range(end, start - 1, -1))
        return []
        
    def _parse_rounds(self, options):
        if options.get('rounds'):
            return [int(r.strip()) for r in options['rounds'].split(',')]
        return None

    def _write_log(self, completed, failed, sessions, start_time, failed_list):
        # Write to the backend root directory
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'seed_log.txt')
        elapsed = int(time.time() - start_time)
        try:
            with open(log_path, 'a') as f:
                f.write(f"[{timezone.now()}] PROGRESS UPDATE\n")
                f.write(f"  Rounds Completed: {completed}\n")
                f.write(f"  Rounds Failed:    {failed}\n")
                f.write(f"  Total Sessions:   {sessions}\n")
                f.write(f"  Time Elapsed:     {elapsed}s\n")
                if failed_list:
                    f.write(f"  Failed List:      {', '.join(failed_list)}\n")
                f.write("-" * 40 + "\n")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Failed to write log: {e}"))
