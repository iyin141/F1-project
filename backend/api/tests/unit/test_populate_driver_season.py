import pytest

from api.drivers.services import season


SAMPLE_RACE = [
    {
        "round": "1",
        "raceName": "Test GP",
        "Circuit": {"Location": {"locality": "Testville"}},
        "date": "2023-03-01",
        "Results": [
            {
                "position": "1",
                "grid": "1",
                "points": "25",
                "status": "Finished",
                "FastestLap": {},
                "laps": "56",
            }
        ],
    }
]


@pytest.mark.unit
def test_get_driver_season_with_code(monkeypatch):
    # Simulate resolver returning Jolpica id for HAM
    monkeypatch.setattr(season, "resolve_driver_metadata", lambda code, year: {"driver_id": "hamilton", "code": "HAM"})
    monkeypatch.setattr(season, "fetch_season_results", lambda year, did: SAMPLE_RACE)
    monkeypatch.setattr(season, "fetch_season_qualifying", lambda year, did: [])
    monkeypatch.setattr(season, "fetch_season_sprint", lambda year, did: [])
    monkeypatch.setattr(season, "get_season_driver_map", lambda year: {"hamilton": {"name": "Lewis Hamilton"}})

    res = season.get_driver_season("HAM", 2023)
    assert res["total_races"] == 1
    assert res["driver_name"] == "Lewis Hamilton"


@pytest.mark.unit
def test_get_driver_season_with_surname(monkeypatch):
    # Simulate DB resolver returning None but resolve_driver_id finds id
    monkeypatch.setattr(season, "resolve_driver_metadata", lambda code, year: None)
    monkeypatch.setattr(season, "resolve_driver_id", lambda code, year: "hamilton")
    monkeypatch.setattr(season, "fetch_season_results", lambda year, did: SAMPLE_RACE)
    monkeypatch.setattr(season, "fetch_season_qualifying", lambda year, did: [])
    monkeypatch.setattr(season, "fetch_season_sprint", lambda year, did: [])
    monkeypatch.setattr(season, "get_season_driver_map", lambda year: {"hamilton": {"name": "Lewis Hamilton"}})

    res = season.get_driver_season("Hamilton", 2023)
    assert res["total_races"] == 1
    assert res["driver_name"] == "Lewis Hamilton"
