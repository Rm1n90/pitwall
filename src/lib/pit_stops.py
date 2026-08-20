"""Pit stop times.

F1 publishes how long each stop took: the stationary time in the box and the
total time spent in the pit lane. It is not part of the SignalR subscription,
but it is in the public timing archive, so a replay can fetch it for a past
session and a live session can poll it alongside everything else.
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.request import urlopen

STATIC_BASE_URL = "https://livetiming.formula1.com/static/"
FEED_NAME = "PitStopSeries"
REQUEST_TIMEOUT = 20

# A stop shorter or longer than this is not a normal stop; the feed
# occasionally carries a placeholder.
MIN_STATIONARY_S = 0.5
MAX_STATIONARY_S = 120.0


@dataclass(frozen=True)
class PitStop:
    """One pit stop.

    Attributes:
        lap: Lap the driver came in on.
        stationary_s: Time stopped in the box, which is the number quoted on
            television.
        pit_lane_s: Total time between entering and leaving the pit lane.
    """

    lap: Optional[int]
    stationary_s: Optional[float]
    pit_lane_s: Optional[float]


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_pit_stop_series(payload) -> Dict[str, List[PitStop]]:
    """Return ``{car_number: [PitStop, ...]}`` from a feed payload.

    Accepts both the whole feed and a single update, since the live stream
    sends increments of the same shape. Malformed entries are skipped rather
    than raising: a missing pit time is not worth losing a session over.
    """
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("PitTimes")
    if not isinstance(entries, dict):
        return {}

    stops: Dict[str, List[PitStop]] = {}
    for number, records in entries.items():
        if isinstance(records, dict):
            # Live updates arrive keyed by index rather than as a list.
            records = [records[key] for key in sorted(records, key=str)]
        if not isinstance(records, list):
            continue

        for record in records:
            if not isinstance(record, dict):
                continue
            detail = record.get("PitStop") if "PitStop" in record else record
            if not isinstance(detail, dict):
                continue

            stationary = _number(detail.get("PitStopTime"))
            if stationary is not None and not (
                    MIN_STATIONARY_S <= stationary <= MAX_STATIONARY_S):
                stationary = None

            lap = _number(detail.get("Lap"))
            stops.setdefault(str(number), []).append(PitStop(
                lap=int(lap) if lap is not None else None,
                stationary_s=stationary,
                pit_lane_s=_number(detail.get("PitLaneTime")),
            ))
    return stops


def fetch_pit_stops(session_path: str) -> Dict[str, List[PitStop]]:
    """Download the pit stop times for a session feed path.

    Returns an empty mapping if the feed is unavailable, which is normal for
    sessions with no stops and for very old seasons.
    """
    base = session_path if session_path.endswith("/") else session_path + "/"
    url = f"{STATIC_BASE_URL}{base}{FEED_NAME}.json"
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
    except Exception as e:
        print(f"Pit stop times unavailable: {e}")
        return {}
    return parse_pit_stop_series(payload)


def session_feed_path(session) -> Optional[str]:
    """Return the archive feed path for a loaded FastF1 session."""
    try:
        from src.live.schedule import build_session_path

        return build_session_path(
            session.event["EventDate"], session.event["EventName"],
            session.date, session.name,
        )
    except Exception as e:
        print(f"Could not work out the feed path for this session: {e}")
        return None


def stops_by_code(session, stops: Dict[str, List[PitStop]]
                  ) -> Dict[str, List[PitStop]]:
    """Re-key stops from car numbers to the driver codes used in frames."""
    by_code: Dict[str, List[PitStop]] = {}
    for number, entries in stops.items():
        try:
            code = session.get_driver(str(number))["Abbreviation"]
        except Exception:
            continue
        by_code[str(code)] = entries
    return by_code


def fetch_for_session(session) -> Dict[str, List[PitStop]]:
    """Fetch a session's pit stop times, keyed by driver code."""
    path = session_feed_path(session)
    if not path:
        return {}
    return stops_by_code(session, fetch_pit_stops(path))
