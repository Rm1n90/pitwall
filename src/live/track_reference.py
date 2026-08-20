"""Track geometry for a live session.

The replay window draws the circuit from a reference lap: a telemetry frame
with ``X``, ``Y``, ``Distance`` and ``DRS`` columns. During a live session no
lap of the current session is complete yet (and even mid-race, downloading one
would cost minutes), so the reference is taken from an earlier session at the
same circuit and cached on disk.

Position coordinates are stable per circuit across sessions and seasons, so a
lap from last year's qualifying lines up with today's live positions.
"""

import os
import pickle
from typing import List, Optional, Tuple

CACHE_SUBDIR = "track_reference"

# Columns the replay window actually reads from a reference lap. Keeping only
# these turns a FastF1 telemetry frame, which holds a reference to the whole
# loaded session, into a small standalone table.
REQUIRED_COLUMNS = ("X", "Y", "Z", "DRS", "Distance", "RelativeDistance",
                    "Speed")

# Session codes tried in order. Qualifying first because DRS zones are only
# reliably marked on a qualifying lap.
CURRENT_WEEKEND_ORDER = ("Q", "SQ", "FP3", "FP2", "FP1", "S", "R")
PREVIOUS_YEAR_ORDER = ("Q", "R")

# How many previous seasons to search before giving up.
MAX_YEARS_BACK = 4


class TrackReference:
    """Reference geometry used to draw the circuit and place cars.

    Attributes:
        example_lap: Telemetry frame with ``X``/``Y``/``Distance``/``DRS``.
        rotation: Circuit rotation in degrees, as FastF1 reports it.
        length_m: Lap length in metres.
        description: Human readable note about where the reference came from.
    """

    def __init__(self, example_lap, rotation: float, length_m: float,
                 description: str):
        self.example_lap = example_lap
        self.rotation = rotation
        self.length_m = length_m
        self.description = description

    def bounds(self) -> Tuple[float, float, float, float]:
        xs = self.example_lap["X"]
        ys = self.example_lap["Y"]
        return float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())


def _cache_path(cache_dir: str, event_key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in event_key)
    return os.path.join(cache_dir, CACHE_SUBDIR, f"{safe}.pkl")


def _load_cached(path: str) -> Optional[TrackReference]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            payload = pickle.load(handle)
        return TrackReference(
            payload["example_lap"], payload["rotation"],
            payload["length_m"], payload["description"] + " (cached)",
        )
    except Exception as exc:
        print(f"[live] ignoring unreadable track reference cache: {exc}")
        return None


def _save_cached(path: str, reference: TrackReference) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump({
                "example_lap": reference.example_lap,
                "rotation": reference.rotation,
                "length_m": reference.length_m,
                "description": reference.description,
            }, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        print(f"[live] could not cache track reference: {exc}")


def _to_plain_frame(telemetry):
    """Reduce a FastF1 telemetry frame to a small, standalone DataFrame.

    FastF1's ``Telemetry`` keeps a reference back to the loaded session, so
    pickling one as-is drags the entire session along with it (tens of
    megabytes). Only the columns the replay reads are kept.
    """
    import pandas as pd

    columns = [name for name in REQUIRED_COLUMNS if name in telemetry]
    return pd.DataFrame(
        {name: telemetry[name].to_numpy() for name in columns}
    )


def _reference_from_session(year: int, event, session_code: str
                            ) -> Optional[TrackReference]:
    """Load one candidate session and extract its fastest lap telemetry."""
    import fastf1

    try:
        session = fastf1.get_session(year, event, session_code)
        session.load(telemetry=True, weather=False, messages=False)
    except Exception:
        return None

    try:
        if session.laps is None or len(session.laps) == 0:
            return None
        fastest = session.laps.pick_fastest()
        if fastest is None:
            return None
        telemetry = fastest.get_telemetry()
    except Exception:
        return None

    if telemetry is None or telemetry.empty:
        return None
    if "X" not in telemetry or "Y" not in telemetry:
        return None
    if "DRS" not in telemetry:
        # DRS was removed from the feed for the 2026 regulations.
        telemetry = telemetry.assign(DRS=0)

    telemetry = _to_plain_frame(telemetry)

    try:
        rotation = float(session.get_circuit_info().rotation)
    except Exception:
        rotation = 0.0

    length_m = float(telemetry["Distance"].max()) \
        if "Distance" in telemetry else 0.0

    return TrackReference(
        telemetry, rotation, length_m,
        f"{year} {event} {session_code} fastest lap",
    )


def _candidates(year: int, event, current_weekend: bool) -> List[Tuple[int, str]]:
    order = CURRENT_WEEKEND_ORDER if current_weekend else PREVIOUS_YEAR_ORDER
    return [(year, code) for code in order]


def get_track_reference(year: int, event, cache_dir: str = "computed_data",
                        event_key: Optional[str] = None,
                        refresh: bool = False) -> Optional[TrackReference]:
    """Return drawable track geometry for ``event`` in ``year``.

    Earlier sessions of the same weekend are preferred; if none has usable
    telemetry yet (typical before FP1 finishes) previous seasons are tried.

    Args:
        year: Season of the live event.
        event: Event name or round number accepted by ``fastf1.get_session``.
        cache_dir: Directory holding the on-disk cache.
        event_key: Cache key; defaults to ``"<event> <year>"``.
        refresh: Ignore any cached reference and rebuild it.

    Returns:
        A :class:`TrackReference`, or ``None`` when no source could be found.
    """
    key = event_key or f"{event}_{year}"
    path = _cache_path(cache_dir, key)

    if not refresh:
        cached = _load_cached(path)
        if cached is not None:
            return cached

    attempts = _candidates(year, event, current_weekend=True)
    for offset in range(1, MAX_YEARS_BACK + 1):
        attempts.extend(_candidates(year - offset, event, current_weekend=False))

    for attempt_year, code in attempts:
        reference = _reference_from_session(attempt_year, event, code)
        if reference is None:
            continue
        print(f"[live] track layout from {reference.description}")
        _save_cached(path, reference)
        return reference

    print(f"[live] no track reference could be built for {event} {year}")
    return None


def positions_look_aligned(reference: TrackReference, points, tolerance=1.6
                           ) -> bool:
    """Sanity-check live positions against the reference bounding box.

    A mismatch means the reference lap uses different coordinates from the
    live feed, which would put every car in the wrong place. Callers use this
    to warn rather than silently drawing nonsense.
    """
    if not points:
        return True
    x_min, x_max, y_min, y_max = reference.bounds()
    width = max(1.0, x_max - x_min)
    height = max(1.0, y_max - y_min)
    margin_x = width * (tolerance - 1.0)
    margin_y = height * (tolerance - 1.0)
    inside = sum(
        1 for x, y in points
        if x_min - margin_x <= x <= x_max + margin_x
        and y_min - margin_y <= y <= y_max + margin_y
    )
    return inside >= max(1, len(points) // 2)
