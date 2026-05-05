"""Service layer for driver career and season data."""
import logging
from datetime import datetime

import requests

from api.models import DriverStandings, RaceResultData, SeasonSchedule

logger = logging.getLogger(__name__)

JOLPICA_DRIVERS_URL = "https://api.jolpi.ca/ergast/f1/drivers/"
JOLPICA_SEASON_DRIVER_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/driverStandings/"
JOLPICA_SEASON_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/results/"
JOLPICA_SEASON_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/{year}/driverStandings/"
JOLPICA_SEASON_URL = "https://api.jolpi.ca/ergast/f1/{year}/"
REQUEST_TIMEOUT = 20


KNOWN_DRIVER_CODE_TO_ID = {
    "HAM": "hamilton",
    "VER": "verstappen",
    "LEC": "leclerc",
    "SAI": "sainz",
    "NOR": "norris",
    "PIA": "piastri",
    "RUS": "russell",
    "ALO": "alonso",
    "STR": "stroll",
    "ALB": "albon",
    "OCO": "ocon",
    "GAS": "gasly",
    "HUL": "hulkenberg",
    "MAG": "kevin_magnussen",
    "TSU": "tsunoda",
    "LAW": "lawson",
    "BOT": "bottas",
    "ZHO": "zhou",
    "PER": "perez",
}


class DriverCareerService:
    """Service for fetching driver career and season data."""

    _driver_id_cache = dict(KNOWN_DRIVER_CODE_TO_ID)

    def get_driver_career(self, driver_code):
        """
        Get full career summary for a driver.
        Returns list of seasons with stats, sorted by year descending.
        DB-first: reads from DriverSeasonSummary.
        Fallback: Jolpica driverStandings endpoint.
        """
        career_data = []
        driver_name = None
        nationality = None

        # Step 1: Try DB first
        db_seasons = self._get_career_from_db(driver_code)
        if db_seasons:
            career_data.extend(db_seasons)
            if db_seasons:
                driver_name = db_seasons[0].get("driver_name")
                nationality = db_seasons[0].get("nationality")

        # Step 2: Fill missing seasons from Jolpica
        jolpica_seasons = self._get_career_from_jolpica(driver_code)
        if jolpica_seasons:
            # Get years already in DB
            db_years = {s["year"] for s in db_seasons}
            # Add Jolpica seasons that are not in DB
            for season in jolpica_seasons:
                if season["year"] not in db_years:
                    career_data.append(season)
            if jolpica_seasons and not driver_name:
                driver_name = jolpica_seasons[0].get("driver_name")
                nationality = jolpica_seasons[0].get("nationality")

        # Sort by year descending
        career_data.sort(key=lambda x: x["year"], reverse=True)

        # Compute career totals
        career_totals = self._compute_career_totals(career_data)

        message = None if career_data else "No career data available from persistence or Jolpica"
        return {
            "driver_code": driver_code,
            "driver_name": driver_name,
            "nationality": nationality,
            "career": career_data,
            "career_totals": career_totals,
            "message": message,
        }

    def get_driver_season(self, driver_code, year):
        """
        Get race-by-race breakdown for one driver in one season.
        DB-first for persisted results.
        FastF1 fallback for missing rounds.
        """
        races = []
        driver_name = None
        constructor = None
        final_position = None
        final_points = None

        # Step 1: Get season schedule
        schedule = self._get_season_schedule(year)
        if not schedule:
            return {
                "driver_code": driver_code,
                "driver_name": None,
                "year": year,
                "constructor": None,
                "final_position": None,
                "final_points": None,
                "races": [],
            }

        # Step 2: Get non-DB fallback results once to avoid per-round network calls
        jolpica_results_by_round = self._get_season_results_from_jolpica(driver_code, year)

        # Step 3: Get results per round (DB-first, then Jolpica fallback)
        for race_info in schedule:
            round_data = self._get_round_result(
                driver_code,
                year,
                race_info["round"],
                fallback_results=jolpica_results_by_round,
            )
            if round_data:
                races.append({**race_info, **round_data})
                if not driver_name:
                    driver_name = round_data.get("driver_name")
                if not constructor:
                    constructor = round_data.get("constructor")

        # Step 4: Get season standing (championship position and points)
        standing = self._get_season_standing(driver_code, year)
        if standing:
            final_position = standing.get("position")
            final_points = standing.get("points")
            if not driver_name:
                driver_name = standing.get("driver_name")
            if not constructor:
                constructor = standing.get("constructor")

        message = None if races else f"No season data available from persistence or Jolpica for {driver_code} in {year}"
        return {
            "driver_code": driver_code,
            "driver_name": driver_name,
            "year": year,
            "constructor": constructor,
            "final_position": final_position,
            "final_points": final_points,
            "races": races,
            "message": message,
        }

    def _get_career_from_db(self, driver_code):
        """Query DriverStandings for all seasons of this driver."""
        try:
            rows = DriverStandings.objects.filter(
                driver_code=driver_code, year__isnull=False
            ).order_by("-year")
            result = []
            for row in rows:
                p = row.payload
                result.append({
                    "year": row.year,
                    "constructor": p.get("constructor", ""),
                    "position": p.get("position"),
                    "points": float(p.get("points", 0)),
                    "wins": int(p.get("wins", 0)),
                    "podiums": int(p.get("podiums", 0)),
                    "poles": int(p.get("poles", 0)),
                    "fastest_laps": int(p.get("fastest_laps", 0)),
                    "races_entered": int(p.get("races_entered", 0)),
                    "dnfs": int(p.get("dnfs", 0)),
                })
            return result
        except Exception as e:
            logger.error(f"Error querying DB for career {driver_code}: {e}")
            return []

    def _resolve_driver_id(self, driver_code):
        """Resolve FIA code (e.g. HAM) to Jolpica driverId (e.g. hamilton)."""
        code = (driver_code or "").upper()
        if code in self._driver_id_cache:
            return self._driver_id_cache[code]

        try:
            response = requests.get(JOLPICA_DRIVERS_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            drivers = data.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
            for driver in drivers:
                if (driver.get("code") or "").upper() == code:
                    driver_id = driver.get("driverId")
                    if driver_id:
                        self._driver_id_cache[code] = driver_id
                        return driver_id
        except requests.RequestException as exc:
            logger.warning(f"Could not resolve driverId for {driver_code}: {exc}")
        except Exception as exc:
            logger.error(f"Unexpected error resolving driverId for {driver_code}: {exc}")
        return None

    def _parse_driver_standing_payload(self, payload, driver_code):
        """Parse Jolpica standings payload (StandingsLists/DriverStandings)."""
        standings_table = payload.get("MRData", {}).get("StandingsTable", {})
        all_lists = standings_table.get("StandingsLists") or standings_table.get("StandingsList") or []
        parsed = []
        for standings_list in all_lists:
            year = standings_list.get("season") or standings_table.get("season")
            if not year:
                continue
            driver_rows = standings_list.get("DriverStandings") or standings_list.get("Standings") or []
            for row in driver_rows:
                driver_info = row.get("Driver", {})
                code = (driver_info.get("code") or "").upper()
                if code and code != driver_code.upper():
                    continue
                constructor_list = row.get("Constructors", [])
                constructor_name = constructor_list[0].get("name", "") if constructor_list else ""
                parsed.append(
                    {
                        "year": int(year),
                        "constructor": constructor_name,
                        "position": int(row.get("position", 0)) if row.get("position") else None,
                        "points": float(row.get("points", 0)),
                        "wins": int(row.get("wins", 0)),
                        "podiums": 0,
                        "poles": 0,
                        "fastest_laps": 0,
                        "races_entered": 0,
                        "dnfs": 0,
                        "driver_name": f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip() or None,
                        "nationality": driver_info.get("nationality"),
                    }
                )
        return parsed

    def _get_career_from_jolpica(self, driver_code):
        """Fetch career data from Jolpica by season standings."""
        driver_id = self._resolve_driver_id(driver_code)
        if not driver_id:
            return []

        seasons = []
        current_year = datetime.now().year
        network_errors = 0
        for year in range(1950, current_year + 1):
            try:
                url = JOLPICA_SEASON_DRIVER_STANDINGS_URL.format(year=year, driver_id=driver_id)
                response = requests.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                season_rows = self._parse_driver_standing_payload(response.json(), driver_code)
                seasons.extend(season_rows)
                network_errors = 0
            except requests.RequestException as exc:
                # Avoid long request chains when the remote service is down.
                network_errors += 1
                if network_errors >= 3:
                    logger.warning(
                        "Stopping Jolpica career fetch for %s after repeated network errors: %s",
                        driver_code,
                        exc,
                    )
                    break
            except Exception as exc:
                logger.error(f"Error parsing Jolpica career data for {driver_code} in {year}: {exc}")

        return seasons

    def _compute_career_totals(self, seasons):
        """Compute aggregate stats across all seasons."""
        totals = {
            "championships": 0,
            "wins": 0,
            "podiums": 0,
            "poles": 0,
            "fastest_laps": 0,
            "races_entered": 0,
            "dnfs": 0,
            "total_points": 0,
        }

        for season in seasons:
            if season.get("position") == 1:
                totals["championships"] += 1
            totals["wins"] += season.get("wins", 0)
            totals["podiums"] += season.get("podiums", 0)
            totals["poles"] += season.get("poles", 0)
            totals["fastest_laps"] += season.get("fastest_laps", 0)
            totals["races_entered"] += season.get("races_entered", 0)
            totals["dnfs"] += season.get("dnfs", 0)
            totals["total_points"] += season.get("points", 0)

        return totals

    def _get_season_schedule(self, year):
        """Get all races for a given season from SeasonSchedule or Jolpica."""
        try:
            record = SeasonSchedule.objects.filter(year=year).first()
            if record:
                races = record.payload.get("races", [])
                if races:
                    return [
                        {
                            "year": year,
                            "round": r.get("round"),
                            "race_name": r.get("name", ""),
                            "location": r.get("location"),
                            "race_date": r.get("date"),
                        }
                        for r in races
                    ]
            return self._get_schedule_from_jolpica(year)
        except Exception as e:
            logger.warning(f"Error getting schedule from DB for {year}, falling back to Jolpica: {e}")
            return self._get_schedule_from_jolpica(year)

    def _get_schedule_from_jolpica(self, year):
        """Fetch race schedule from Jolpica."""
        try:
            url = JOLPICA_SEASON_URL.format(year=year)
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            races = []
            if "MRData" in data and "RaceTable" in data["MRData"]:
                for race in data["MRData"]["RaceTable"].get("Races", []):
                    races.append({
                        "year": year,
                        "round": int(race.get("round", 0)),
                        "race_name": race.get("raceName", race.get("name", "")),
                        "location": race.get("Circuit", {}).get("Location", {}).get("locality", ""),
                        "race_date": race.get("date"),
                    })
            return races
        except Exception as e:
            logger.warning(f"Jolpica schedule request failed for {year}: {e}")
            return []

    def _get_round_result(self, driver_code, year, round_number, fallback_results=None):
        """
        Get this driver's result for one round.
        DB-first: check persisted RaceResultData payload.
        Fallback: Jolpica results passed in.
        """
        try:
            record = RaceResultData.objects.filter(
                year=year, round_number=round_number, session="R"
            ).first()
            if record:
                for result in record.payload.get("results", []):
                    if (result.get("driver_code") or "").upper() == driver_code.upper():
                        return {
                            "grid_position": result.get("grid_position"),
                            "finish_position": result.get("position"),
                            "points": float(result.get("points", 0)),
                            "status": result.get("status"),
                            "fastest_lap": result.get("fastest_lap", False),
                            "laps_completed": result.get("laps"),
                            "driver_name": result.get("driver_name"),
                            "constructor": result.get("team"),
                            "qualifying_position": None,
                            "qualifying_time": None,
                        }

            if fallback_results:
                return fallback_results.get(round_number)
            return None
        except Exception as e:
            if fallback_results:
                logger.debug(
                    "DB round result unavailable for %s/%s/%s, used Jolpica fallback: %s",
                    driver_code, year, round_number, e,
                )
                return fallback_results.get(round_number)
            logger.error(f"Error querying round result {driver_code}/{year}/{round_number}: {e}")
            return None

    def _get_season_results_from_jolpica(self, driver_code, year):
        """Fetch season results from Jolpica and map by round number."""
        driver_id = self._resolve_driver_id(driver_code)
        if not driver_id:
            return {}

        try:
            url = JOLPICA_SEASON_RESULTS_URL.format(year=year, driver_id=driver_id)
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])

            mapped = {}
            for race in races:
                results = race.get("Results", [])
                if not results:
                    continue
                result = results[0]
                driver_info = result.get("Driver", {})
                constructor = result.get("Constructor", {})
                fastest_lap = bool(result.get("FastestLap"))
                round_number = int(race.get("round", 0))
                mapped[round_number] = {
                    "grid_position": int(result.get("grid", 0)) if result.get("grid") else None,
                    "finish_position": int(result.get("position", 0)) if result.get("position") else None,
                    "points": float(result.get("points", 0)),
                    "status": result.get("status"),
                    "fastest_lap": fastest_lap,
                    "laps_completed": int(result.get("laps", 0)) if result.get("laps") else None,
                    "driver_name": f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip() or None,
                    "constructor": constructor.get("name"),
                    "qualifying_position": None,
                    "qualifying_time": None,
                }
            return mapped
        except requests.RequestException as exc:
            logger.warning(f"Error fetching season results for {driver_code}/{year}: {exc}")
            return {}
        except Exception as exc:
            logger.error(f"Error parsing season results for {driver_code}/{year}: {exc}")
            return {}

    def _get_season_standing(self, driver_code, year):
        """Get final championship standing for this driver in a year."""
        try:
            url = JOLPICA_SEASON_STANDINGS_URL.format(year=year)
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if "MRData" in data and "StandingsTable" in data["MRData"]:
                standings_table = data["MRData"]["StandingsTable"]
                standings_lists = standings_table.get("StandingsLists") or standings_table.get("StandingsList") or []
                for standings_list in standings_lists:
                    standings = standings_list.get("DriverStandings") or standings_list.get("Standings") or []
                    for standing in standings:
                        if standing.get("Driver", {}).get("code", "").upper() == driver_code.upper():
                            driver_info = standing.get("Driver", {})
                            driver_name = f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip()
                            constructor_list = standing.get("Constructors", [])
                            constructor_name = constructor_list[0].get("name", "") if constructor_list else ""

                            return {
                                "position": int(standing.get("position", 0)) if standing.get("position") else None,
                                "points": float(standing.get("points", 0)),
                                "driver_name": driver_name,
                                "constructor": constructor_name,
                            }
            return None
        except Exception as e:
            logger.warning(f"Error fetching season standing for {driver_code}/{year}: {e}")
            return None
