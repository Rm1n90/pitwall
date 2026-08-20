"""Where every driver ran, lap by lap.

The classic race chart plots each driver's position against lap number, so a
whole race reads at a glance: who came through the field, who fell back, when
the stops happened. The data is already published twice over — the timing feed
carries a `LapSeries` topic, and a completed session records a position on
every lap row.
"""

from typing import Dict, List, Optional, Tuple

# Position entries beyond this are not real classifications.
MAX_POSITION = 30


def _position(value) -> Optional[int]:
    try:
        position = int(value)
    except (TypeError, ValueError):
        return None
    return position if 1 <= position <= MAX_POSITION else None


def from_session(session) -> Dict[str, List[Tuple[int, int]]]:
    """Return ``{code: [(lap, position), ...]}`` from a completed session."""
    import pandas as pd

    history: Dict[str, List[Tuple[int, int]]] = {}
    laps = getattr(session, "laps", None)
    if laps is None or laps.empty:
        return history

    for _, lap in laps.iterrows():
        code = str(lap.get("Driver") or "")
        number = lap.get("LapNumber")
        position = _position(lap.get("Position"))
        if not code or position is None or pd.isna(number):
            continue
        history.setdefault(code, []).append((int(number), position))

    for entries in history.values():
        entries.sort()
    return history


def from_lap_series(payload, code_for_number) -> Dict[str, List[Tuple[int, int]]]:
    """Return ``{code: [(lap, position), ...]}`` from the LapSeries feed.

    Args:
        payload: The feed's payload, keyed by car number.
        code_for_number: Callable turning a car number into a driver code.
    """
    if not isinstance(payload, dict):
        return {}

    history: Dict[str, List[Tuple[int, int]]] = {}
    for number, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        positions = entry.get("LapPosition")
        if isinstance(positions, dict):
            # Live updates arrive keyed by lap index rather than as a list.
            ordered = []
            for key in sorted(positions, key=lambda k: int(k)
                              if str(k).isdigit() else 0):
                ordered.append((int(key) + 1, positions[key]))
        elif isinstance(positions, list):
            ordered = list(enumerate(positions, start=1))
        else:
            continue

        code = str(code_for_number(str(number)))
        entries = history.setdefault(code, [])
        for lap, value in ordered:
            position = _position(value)
            if position is not None:
                entries.append((lap, position))

    for entries in history.values():
        entries.sort()
    return history


def merge(base: Dict[str, List[Tuple[int, int]]],
          update: Dict[str, List[Tuple[int, int]]]
          ) -> Dict[str, List[Tuple[int, int]]]:
    """Fold an update into an existing history, newest value winning."""
    for code, entries in update.items():
        by_lap = dict(base.get(code, []))
        by_lap.update(dict(entries))
        base[code] = sorted(by_lap.items())
    return base


def to_payload(history: Dict[str, List[Tuple[int, int]]]) -> Dict[str, list]:
    """Return a JSON-friendly form for the telemetry stream."""
    return {code: [[lap, position] for lap, position in entries]
            for code, entries in history.items()}


def positions_at(history: Dict[str, List[Tuple[int, int]]],
                 lap: int) -> Dict[str, int]:
    """Return each driver's position as at ``lap``."""
    result = {}
    for code, entries in history.items():
        latest = None
        for entry_lap, position in entries:
            if entry_lap > lap:
                break
            latest = position
        if latest is not None:
            result[code] = latest
    return result


def places_gained(history: Dict[str, List[Tuple[int, int]]]
                  ) -> Dict[str, int]:
    """Return how many places each driver made up over the whole session."""
    gained = {}
    for code, entries in history.items():
        if len(entries) < 2:
            continue
        gained[code] = entries[0][1] - entries[-1][1]
    return gained
