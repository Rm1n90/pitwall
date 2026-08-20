"""Championship standings.

The timing feed says nothing about the championship, only about the session in
front of you. Jolpica, the maintained successor to Ergast, has the standings
and needs no key. During a race the feed does carry a projection of where the
championship would stand if the race ended now, which is worth showing beside
the real thing.
"""

import json
import os
import pickle
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

BASE_URL = "https://api.jolpi.ca/ergast/f1"
REQUEST_TIMEOUT = 25
USER_AGENT = "pitwall"

CACHE_SUBDIR = "standings"
# Standings only change when a race finishes, so a day-old copy is fine and
# saves hammering a free service.
CACHE_MAX_AGE_S = 24 * 3600


@dataclass(frozen=True)
class Standing:
    """One row of a championship table.

    Attributes:
        position: Championship position.
        name: Driver code, or constructor name.
        full_name: Driver's full name; empty for a constructor.
        team: Constructor the driver races for; empty for a constructor row.
        points: Championship points.
        wins: Race wins so far.
    """

    position: int
    name: str
    points: float
    wins: int = 0
    full_name: str = ""
    team: str = ""


def _get(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_driver_standings(payload: dict) -> List[Standing]:
    """Return driver standings from a Jolpica response."""
    try:
        lists = payload["MRData"]["StandingsTable"]["StandingsLists"]
    except (KeyError, TypeError):
        return []
    if not lists:
        return []

    standings = []
    for row in lists[0].get("DriverStandings", []):
        driver = row.get("Driver") or {}
        teams = row.get("Constructors") or [{}]
        standings.append(Standing(
            position=int(_number(row.get("position"), 99)),
            name=str(driver.get("code") or driver.get("driverId") or "?"),
            full_name=f"{driver.get('givenName', '')} "
                      f"{driver.get('familyName', '')}".strip(),
            team=str(teams[0].get("name") or ""),
            points=_number(row.get("points")),
            wins=int(_number(row.get("wins"))),
        ))
    return standings


def parse_constructor_standings(payload: dict) -> List[Standing]:
    """Return constructor standings from a Jolpica response."""
    try:
        lists = payload["MRData"]["StandingsTable"]["StandingsLists"]
    except (KeyError, TypeError):
        return []
    if not lists:
        return []

    standings = []
    for row in lists[0].get("ConstructorStandings", []):
        team = row.get("Constructor") or {}
        standings.append(Standing(
            position=int(_number(row.get("position"), 99)),
            name=str(team.get("name") or "?"),
            points=_number(row.get("points")),
            wins=int(_number(row.get("wins"))),
        ))
    return standings


def _cache_path(cache_dir: str, key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return os.path.join(cache_dir, CACHE_SUBDIR, f"{safe}.pkl")


def _load_cached(cache_dir: str, key: str) -> Optional[List[Standing]]:
    path = _cache_path(cache_dir, key)
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > CACHE_MAX_AGE_S:
            return None
        with open(path, "rb") as handle:
            return pickle.load(handle)
    except Exception:
        return None


def _save_cached(cache_dir: str, key: str, standings: List[Standing]) -> None:
    path = _cache_path(cache_dir, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump(standings, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"Could not cache standings: {e}")


def fetch_standings(year: int, kind: str = "driver",
                    cache_dir: str = "computed_data") -> List[Standing]:
    """Return championship standings for a season.

    Args:
        year: Season to fetch.
        kind: ``"driver"`` or ``"constructor"``.
        cache_dir: Where to keep the day-old cache.

    Returns an empty list when the service cannot be reached, so a missing
    network never stops a replay.
    """
    key = f"{year}_{kind}"
    cached = _load_cached(cache_dir, key)
    if cached is not None:
        return cached

    endpoint = "constructorStandings" if kind == "constructor" \
        else "driverStandings"
    try:
        payload = _get(f"{BASE_URL}/{year}/{endpoint}.json?limit=100")
    except Exception as e:
        print(f"Championship standings unavailable: {e}")
        return []

    standings = (parse_constructor_standings(payload)
                 if kind == "constructor" else parse_driver_standings(payload))
    if standings:
        _save_cached(cache_dir, key, standings)
    return standings


def parse_prediction(payload) -> Dict[str, Dict[str, dict]]:
    """Return the live championship projection from the timing feed.

    The feed says where each driver and team would stand if the session ended
    now. Returns ``{"drivers": {...}, "teams": {...}}`` keyed by car number
    and team name.
    """
    if not isinstance(payload, dict):
        return {"drivers": {}, "teams": {}}

    def _rows(section):
        entries = payload.get(section)
        if not isinstance(entries, dict):
            return {}
        cleaned = {}
        for key, row in entries.items():
            if not isinstance(row, dict):
                continue
            cleaned[str(key)] = {
                "current_position": row.get("CurrentPosition"),
                "predicted_position": row.get("PredictedPosition"),
                "current_points": row.get("CurrentPoints"),
                "predicted_points": row.get("PredictedPoints"),
            }
        return cleaned

    return {"drivers": _rows("Drivers"), "teams": _rows("Teams")}
