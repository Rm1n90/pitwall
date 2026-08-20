"""Working out where the pit lane is.

No feed describes the pit lane, but the cars trace it every time they use it.
The timing data records when a driver enters and rejoins, and their position
telemetry in between is the pit lane. Every stop in a race gives an
independent trace, so taking the middle one filters out anything odd.

The result is cached per circuit, and a session whose position feed is too
degraded to trace is skipped in favour of an earlier one at the same circuit.
"""

import math
import os
import pickle
from typing import List, Optional, Sequence, Tuple

CACHE_SUBDIR = "pit_lane"

# A pit lane is a few hundred metres. Anything outside this is not one, which
# is how a session with a broken position feed gets rejected: its cars appear
# not to move at all, giving traces of zero length.
MIN_LANE_M = 80.0
MAX_LANE_M = 1500.0

# A stop shorter or longer than this is not a normal pit visit.
MIN_VISIT_S = 5.0
MAX_VISIT_S = 120.0

# Traces with fewer samples than this are too coarse to draw.
MIN_TRACE_POINTS = 20

# Enough independent traces to trust the middle one.
MIN_TRACES = 3

# Seasons to look back through when the current one cannot be traced.
MAX_YEARS_BACK = 4

_SMOOTHING = 9


def _path_length(points: Sequence[Tuple[float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(points, points[1:]))


def _smooth(points, window: int = _SMOOTHING):
    """Average out telemetry wobble along the path."""
    import numpy as np

    array = np.asarray(points, dtype=float)
    if array.shape[0] <= window:
        return [(float(x), float(y)) for x, y in array]
    kernel = np.ones(window) / window
    xs = np.convolve(array[:, 0], kernel, "valid")
    ys = np.convolve(array[:, 1], kernel, "valid")
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def extract_from_session(session) -> Optional[List[Tuple[float, float]]]:
    """Trace the pit lane from every pit visit in a loaded session.

    Returns ``None`` when the session has too few usable visits, which is what
    happens if its position feed has degraded.
    """
    import numpy as np
    import pandas as pd

    traces = []
    for number in getattr(session, "drivers", []):
        laps = session.laps.pick_drivers(number).sort_values("LapNumber")
        rows = list(laps.iterrows())

        for index, (_, lap) in enumerate(rows):
            entered = lap.get("PitInTime")
            if pd.isna(entered):
                continue
            # The rejoin is recorded on a later lap, never the same one.
            rejoined = None
            for _, following in rows[index + 1:index + 3]:
                if pd.notna(following.get("PitOutTime")):
                    rejoined = following["PitOutTime"]
                    break
            if rejoined is None:
                continue

            start = entered.total_seconds()
            end = rejoined.total_seconds()
            if not (MIN_VISIT_S < end - start < MAX_VISIT_S):
                continue

            try:
                telemetry = laps.iloc[index:index + 2].get_telemetry()
            except Exception:
                continue

            times = telemetry["SessionTime"].dt.total_seconds().to_numpy()
            inside = (times >= start) & (times <= end)
            if inside.sum() < MIN_TRACE_POINTS:
                continue

            traces.append(np.column_stack((
                telemetry["X"].to_numpy(float)[inside],
                telemetry["Y"].to_numpy(float)[inside],
            )))

    if len(traces) < MIN_TRACES:
        return None

    lengths = [_path_length(trace) / 10.0 for trace in traces]
    order = sorted(range(len(traces)), key=lambda i: lengths[i])
    middle = order[len(order) // 2]

    if not (MIN_LANE_M <= lengths[middle] <= MAX_LANE_M):
        print(f"Pit lane traces look wrong ({lengths[middle]:.0f} m); "
              f"the position feed for this session is probably degraded")
        return None

    return _smooth(traces[middle])


def _cache_path(cache_dir: str, key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
    return os.path.join(cache_dir, CACHE_SUBDIR, f"{safe}.pkl")


def load_cached(cache_dir: str, key: str) -> Optional[List]:
    path = _cache_path(cache_dir, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            return pickle.load(handle)
    except Exception as e:
        print(f"Ignoring unreadable pit lane cache: {e}")
        return None


def save_cached(cache_dir: str, key: str, points: Sequence) -> None:
    path = _cache_path(cache_dir, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            pickle.dump(list(points), handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"Could not cache the pit lane: {e}")


def get_pit_lane(session, year: int, event, cache_dir: str = "computed_data",
                 event_key: Optional[str] = None) -> Optional[List]:
    """Return the circuit's pit lane, tracing and caching it if needed.

    Args:
        session: The loaded session being replayed. Tried first.
        year: Season of that session.
        event: Event name, used to look up earlier seasons as a fallback.
        cache_dir: Where to keep the cache.
        event_key: Cache key; defaults to ``"<event>_<year>"``.
    """
    key = event_key or f"{event}_{year}"
    cached = load_cached(cache_dir, key)
    if cached:
        return cached

    if session is not None:
        points = extract_from_session(session)
        if points:
            save_cached(cache_dir, key, points)
            print(f"Traced the pit lane from this session "
                  f"({len(points)} points)")
            return points

    # This session could not be traced; an earlier one at the same circuit
    # will have the same pit lane.
    import fastf1

    for offset in range(1, MAX_YEARS_BACK + 1):
        try:
            earlier = fastf1.get_session(year - offset, event, "R")
            earlier.load(telemetry=True, weather=False, messages=False)
        except Exception:
            continue
        points = extract_from_session(earlier)
        if points:
            save_cached(cache_dir, key, points)
            print(f"Traced the pit lane from the {year - offset} race "
                  f"({len(points)} points)")
            return points

    print("Could not trace the pit lane for this circuit")
    return None
