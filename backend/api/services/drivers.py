"""
F1 Drivers Service
Fetches driver standings data using Ergast Developer API.
"""
import requests


API_URLS = [
    "https://ergast.com/api/f1/{year}/driverStandings.json",
    "https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json",
]

REQUEST_HEADERS = {
    "User-Agent": "f1-project/1.0 (Django backend)",
    "Accept": "application/json",
}


def get_driver_standings(year):
    """
    Fetch the F1 driver standings for a given year from Ergast API.

    Args:
        year (int): The season year.

    Returns:
        list: List of driver standing dictionaries
    """
    if year is None:
        raise ValueError("year is required")

    data = None
    last_error = None
    for template in API_URLS:
        url = template.format(year=year)
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            if response.status_code == 200:
                data = response.json()
                break
            last_error = f"{url} returned status {response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{url} failed: {exc}"

    if data is None:
        raise Exception(f"Standings API unavailable: {last_error}")

    standings_list = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists")

    if not standings_list:
        return []

    driver_standings = standings_list[0].get("DriverStandings", [])

    return [
        {
            "position": int(d.get("position", 0)),
            "driver_name": f"{d['Driver'].get('givenName', '')} {d['Driver'].get('familyName', '')}".strip(),
            "points": float(d.get("points", 0)),
            "wins": int(d.get("wins", 0)),
            "constructor": d.get("Constructors", [{}])[0].get("name", ""),
        }
        for d in driver_standings
    ]
