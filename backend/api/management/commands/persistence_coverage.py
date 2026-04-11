from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from api.services.coverage import get_persistence_coverage


class Command(BaseCommand):
    help = "Inspect persisted coverage by season/round and DB-first readiness"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Season year, e.g. 2024")
        parser.add_argument("--round", type=int, dest="round_number", help="Optional round number filter")
        parser.add_argument("--json", action="store_true", help="Emit JSON output")

    def handle(self, *args, **options):
        year = options["year"]
        round_number = options.get("round_number")
        as_json = bool(options.get("json"))
        payload = get_persistence_coverage(year, round_number)

        if as_json:
            self.stdout.write(json.dumps(payload, indent=2))
            return

        self.stdout.write(f"Persistence coverage season={year} round={round_number if round_number else 'ALL'}")
        for item in coverage:
            self.stdout.write(
                (
                    f"R{item['round']:02d} {item['race_name']} | status={item['status']} "
                    f"results={item['counts']['results']} stints={item['counts']['stints']} "
                    f"metrics={item['counts']['metrics']} sectors={item['counts']['sectors']} "
                    f"ready={item['db_first_flags']['all_db_first_ready']}"
                )
            )
