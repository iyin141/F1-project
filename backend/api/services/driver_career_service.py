"""Service layer for driver career and season data."""
import logging
from datetime import datetime

import requests

from api.models import DriverCareer, DriverStandings, RaceResultData, SeasonSchedule

logger = logging.getLogger(__name__)

JOLPICA_DRIVERS_URL = "https://api.jolpi.ca/ergast/f1/drivers/"
JOLPICA_SEASON_DRIVER_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/driverStandings/"
JOLPICA_SEASON_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/{year}/drivers/{driver_id}/results/"
JOLPICA_SEASON_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/{year}/driverStandings/"
JOLPICA_SEASON_URL = "https://api.jolpi.ca/ergast/f1/{year}/"
JOLPICA_DRIVER_RESULTS_URL = "https://api.jolpi.ca/ergast/f1/drivers/{driver_id}/results.json"
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

    def get_driver_career(self, driver_code, skip_cache=False):
        """
        Get full career summary for a driver using Jolpica single fetch.
        Returns list of seasons with minimal stats, sorted by year descending.
        """
        driver_code = driver_code.upper()

        if not skip_cache:
            db_record = DriverCareer.objects.filter(driver_code=driver_code).first()
            if db_record and db_record.payload:
                cached = db_record.payload
                career = cached.get("career", [])
                total_races = sum(c.get("races", 0) for c in career)
                if total_races > 0:
                    cached_data = dict(cached)
                    cached_data["driver_code"] = driver_code
                    return cached_data

        driver_id = self._resolve_driver_id(driver_code)
        if not driver_id:
            return {
                "driver_code": driver_code,
                "driver_name": None,
                "nationality": None,
                "career": [],
                "career_totals": {"total_wins": 0, "total_podiums": 0},
                "message": "Driver not found in Jolpica",
            }

        wins = 0
        podiums = 0
        by_year = {}
        driver_name = None
        nationality = None

        try:
            races = self._fetch_all_driver_results(driver_id)

            for race in races:
                year = int(race.get('season', 0))
                if not year:
                    continue

                results = race.get('Results', [])
                if not results:
                    continue

                result = results[0]
                position = int(result.get('position', 0))

                if not driver_name:
                    driver_info = result.get('Driver', {})
                    driver_name = f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip()
                    nationality = driver_info.get('nationality')

                if year not in by_year:
                    by_year[year] = {'wins': 0, 'podiums': 0, 'races': 0}

                by_year[year]['races'] += 1

                if position == 1:
                    wins += 1
                    podiums += 1
                    by_year[year]['wins'] += 1
                    by_year[year]['podiums'] += 1
                elif position in (2, 3):
                    podiums += 1
                    by_year[year]['podiums'] += 1

        except Exception as exc:
            logger.error(f"Error fetching Jolpica career data for {driver_code}: {exc}")
            return {
                "driver_code": driver_code,
                "driver_name": None,
                "nationality": None,
                "career": [],
                "career_totals": {"total_wins": 0, "total_podiums": 0},
                "message": f"Error fetching career data: {exc}",
            }

        career_data = []
        for year, stats in by_year.items():
            career_data.append({
                "year": year,
                "races": stats["races"],
                "wins": stats["wins"],
                "podiums": stats["podiums"],
            })

        career_data.sort(key=lambda x: x["year"], reverse=True)

        result = {
            "driver_code": driver_code,
            "driver_name": driver_name,
            "nationality": nationality,
            "career": career_data,
            "career_totals": {
                "total_wins": wins,
                "total_podiums": podiums,
            },
            "message": None if career_data else "No career data available",
        }

        if career_data:
            DriverCareer.objects.update_or_create(
                driver_code=driver_code,
                defaults={"payload": result}
            )

        return result

    def _fetch_all_driver_results(self, driver_id: str) -> list:
        """Fetch all race results for a driver, paginating through Jolpica."""
        all_races = []
        offset    = 0
        limit     = 100  # Jolpica max per request

        while True:
            url = (
                f"{JOLPICA_DRIVER_RESULTS_URL.format(driver_id=driver_id)}"
                f"?limit={limit}&offset={offset}"
            )
            try:
                response = requests.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data      = response.json().get('MRData', {})
                total     = int(data.get('total', 0))
                races     = data.get('RaceTable', {}).get('Races', [])

                all_races.extend(races)

                # Stop if we've fetched everything
                if offset + limit >= total:
                    break

                offset += limit

            except Exception as e:
                logger.error(f"Pagination error at offset {offset} for {driver_id}: {e}")
                break

        logger.info(f"[Jolpica] Fetched {len(all_races)} total races for {driver_id}")
        return all_races

    def get_driver_season(self, driver_code, year):
        """
        Get full season results for a driver including:
        - Race results
        - Qualifying results
        - Sprint results (if applicable)
        """
        driver_id = self._resolve_driver_id(driver_code)
        if not driver_id:
             return { "driver_code": driver_code.upper(), "driver_name": None, "year": year, "total_races": 0, "sprint_weekends": 0, "races": [], "message": "Driver not found" }
             
        # ── 1. Race Results ────────────────────────────────────────
        race_url  = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{driver_id}/results.json?limit=100"
        try:
            race_data = requests.get(race_url, timeout=REQUEST_TIMEOUT).json()
            races     = race_data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
        except Exception as e:
            logger.error(f"Failed to fetch race results: {e}")
            races = []

        # ── 2. Qualifying Results ──────────────────────────────────
        qual_url  = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{driver_id}/qualifying.json?limit=100"
        try:
            qual_data = requests.get(qual_url, timeout=REQUEST_TIMEOUT).json()
            quali     = qual_data.get('MRData', {}).get('RaceTable', {}).get('Races', [])
        except Exception:
            quali = []

        quali_lookup = {}
        for q in quali:
            round_num = int(q.get('round', 0))
            qr_list   = q.get('QualifyingResults', [])
            if qr_list:
                qr = qr_list[0]
                quali_lookup[round_num] = {
                    "qualifying_position": int(qr.get('position', 0)) if qr.get('position') else None,
                    "qualifying_time": (
                        qr.get('Q3') or
                        qr.get('Q2') or
                        qr.get('Q1')
                    )
                }

        # ── 3. Sprint Results ──────────────────────────────────────
        sprint_url  = f"{JOLPICA_SEASON_URL.format(year=year)}drivers/{driver_id}/sprint.json?limit=100"
        sprint_lookup = {}
        try:
            sprint_resp = requests.get(sprint_url, timeout=REQUEST_TIMEOUT)
            if sprint_resp.status_code == 200:
                sprint_races = sprint_resp.json().get('MRData', {}).get('RaceTable', {}).get('Races', [])
                for s in sprint_races:
                    round_num = int(s.get('round', 0))
                    sr_list   = s.get('SprintResults', [])
                    if sr_list:
                        sr = sr_list[0]
                        sprint_lookup[round_num] = {
                            "sprint_position": int(sr.get('position', 0)) if sr.get('position') else None,
                            "sprint_points":   float(sr.get('points', 0)) if sr.get('points') else None,
                            "sprint_status":   sr.get('status'),
                            "sprint_grid":     int(sr.get('grid', 0)) if sr.get('grid') else None,
                            "sprint_laps":     int(sr.get('laps', 0)) if sr.get('laps') else None,
                            "sprint_fastest_lap": (
                                sr.get('FastestLap', {}).get('rank') == '1'
                            )
                        }
        except Exception:
            pass

        # ── 4. Merge Everything ────────────────────────────────────
        result_races = []
        driver_name = None
        for race in races:
            round_num = int(race.get('round', 0))
            rr_list   = race.get('Results', [])
            if not rr_list:
                continue
            rr = rr_list[0]

            if not driver_name:
                driver_info = rr.get('Driver', {})
                driver_name = f"{driver_info.get('givenName', '')} {driver_info.get('familyName', '')}".strip()

            q_data = quali_lookup.get(round_num, {
                "qualifying_position": None,
                "qualifying_time":     None
            })

            s_data = sprint_lookup.get(round_num, {
                "sprint_position":    None,
                "sprint_points":      None,
                "sprint_status":      None,
                "sprint_grid":        None,
                "sprint_laps":        None,
                "sprint_fastest_lap": None
            })

            fastest_lap = rr.get('FastestLap', {}).get('rank') == '1'
            pos_str = rr.get('position', '')
            finish_position = int(pos_str) if pos_str.isdigit() else None

            result_races.append({
                "year":              year,
                "round":             round_num,
                "race_name":         race.get('raceName', ''),
                "location":          race.get('Circuit', {}).get('Location', {}).get('locality', ''),
                "race_date":         race.get('date'),

                "qualifying_position": q_data["qualifying_position"],
                "qualifying_time":     q_data["qualifying_time"],

                "sprint_position":    s_data["sprint_position"],
                "sprint_points":      s_data["sprint_points"],
                "sprint_status":      s_data["sprint_status"],
                "sprint_grid":        s_data["sprint_grid"],
                "sprint_laps":        s_data["sprint_laps"],
                "sprint_fastest_lap": s_data["sprint_fastest_lap"],

                "grid_position":   int(rr.get('grid', 0)) if rr.get('grid') else None,
                "finish_position": finish_position,
                "points":          float(rr.get('points', 0)) if rr.get('points') else 0.0,
                "status":          rr.get('status'),
                "fastest_lap":     fastest_lap,
                "laps_completed":  int(rr.get('laps', 0)) if rr.get('laps') else None,
            })

        return {
            "driver_code":     driver_code.upper(),
            "driver_name":     driver_name,
            "year":            year,
            "total_races":     len(result_races),
            "sprint_weekends": len(sprint_lookup),
            "races":           result_races,
            "message":         None if result_races else "No season data available",
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
                fastest_lap = result.get('FastestLap', {}).get('rank') == '1'
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
