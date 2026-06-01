"""CLI-callable champions sync functions.

Wraps `ChampionsSyncService` so callers can import simple functions or run
from the command line.
"""
from __future__ import annotations

import argparse
import logging
from typing import Dict

from api.drivers.services.champions_sync_service import ChampionsSyncService

logger = logging.getLogger(__name__)


def sync_year_champion(year: int) -> Dict:
    service = ChampionsSyncService()
    return service.sync_year_champion(int(year))


def sync_all_champions() -> Dict:
    service = ChampionsSyncService()
    return service.sync_all_champions()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync F1 champions from Jolpica")
    parser.add_argument("--year", type=int, help="Sync champion for a specific year")
    parser.add_argument("--all", action="store_true", help="Sync champions for all years")
    args = parser.parse_args(argv)

    if args.all:
        logger.info("Starting full champions sync")
        result = sync_all_champions()
        print(result)
        return 0

    if not args.year:
        parser.error("either --year or --all must be provided")

    result = sync_year_champion(args.year)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
