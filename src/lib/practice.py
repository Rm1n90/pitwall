"""Practice session timing.

A race has a grid, a finishing order and a lap count, and the running order
follows from where the cars are on the track. Practice has none of that. Cars
come and go as the teams please, most laps are in-laps or out-laps, and the
order on the timing screen is simply who has set the quickest lap so far.

This module answers the questions the screen needs: what is a driver's best
lap at a given moment, who is ahead of whom, and how far off the session best
each of them is.
"""

import bisect
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

PRACTICE_SESSIONS = ("FP1", "FP2", "FP3")

# How long a practice session runs. Used only when the feed gives us nothing
# better to count down from.
DEFAULT_PRACTICE_MINUTES = 60


def is_practice(session_type: str) -> bool:
    """Whether ``session_type`` names a practice session."""
    return str(session_type).upper() in PRACTICE_SESSIONS


def practice_label(session_type: str) -> str:
    """The name a timing screen would use, for example ``Practice 1``."""
    name = str(session_type).upper()
    if not is_practice(name):
        return name
    return f"Practice {name[-1]}"


@dataclass(frozen=True)
class CompletedLap:
    """One lap a driver has finished.

    Attributes:
        code: Driver abbreviation.
        lap_number: The driver's own lap count, not the session's.
        lap_time_s: How long the lap took.
        end_time_s: When the lap was completed, on the replay clock.
        deleted: Whether the stewards took the lap away, usually for track
            limits. A deleted lap still counts as mileage but never as a time.
    """

    code: str
    lap_number: int
    lap_time_s: float
    end_time_s: float
    deleted: bool = False


class PracticeTiming:
    """The running order of a practice session, at any moment in it."""

    def __init__(self, laps: Sequence[CompletedLap], codes: Sequence[str]):
        """
        Args:
            laps: Every lap completed in the session, in any order.
            codes: Driver abbreviations, in the order to fall back on before
                anybody has set a time.
        """
        self._codes = list(codes)
        self._rank = {code: index for index, code in enumerate(self._codes)}

        # Per driver: the times at which their best lap improved, and what it
        # improved to. Both are ascending, so a lookup is one bisect.
        self._improve_at: Dict[str, List[float]] = {c: [] for c in self._codes}
        self._improve_to: Dict[str, List[float]] = {c: [] for c in self._codes}
        # Per driver: when each lap was completed, deleted laps included.
        self._lap_ends: Dict[str, List[float]] = {c: [] for c in self._codes}

        ordered = sorted(laps, key=lambda lap: (lap.end_time_s, lap.lap_number))
        best: Dict[str, float] = {}
        for lap in ordered:
            if lap.code not in self._rank:
                continue
            self._lap_ends[lap.code].append(lap.end_time_s)
            if lap.deleted or lap.lap_time_s is None or lap.lap_time_s <= 0:
                continue
            if lap.code in best and lap.lap_time_s >= best[lap.code]:
                continue
            best[lap.code] = lap.lap_time_s
            self._improve_at[lap.code].append(lap.end_time_s)
            self._improve_to[lap.code].append(lap.lap_time_s)

        # The session best improves whenever anybody's best does.
        self._session_at: List[float] = []
        self._session_to: List[float] = []
        running = None
        for lap in ordered:
            if lap.deleted or lap.lap_time_s is None or lap.lap_time_s <= 0:
                continue
            if running is not None and lap.lap_time_s >= running:
                continue
            running = lap.lap_time_s
            self._session_at.append(lap.end_time_s)
            self._session_to.append(lap.lap_time_s)

    @staticmethod
    def _value_at(times: List[float], values: List[float],
                  t: float) -> Optional[float]:
        """The last value whose time is at or before ``t``."""
        index = bisect.bisect_right(times, t) - 1
        return None if index < 0 else values[index]

    def best_at(self, code: str, t: float) -> Optional[float]:
        """A driver's best lap time as at ``t``, or ``None`` if they have none."""
        return self._value_at(self._improve_at.get(code, []),
                              self._improve_to.get(code, []), t)

    def session_best_at(self, t: float) -> Optional[float]:
        """The quickest lap anyone has set as at ``t``."""
        return self._value_at(self._session_at, self._session_to, t)

    def gap_at(self, code: str, t: float) -> Optional[float]:
        """How far a driver's best lap is off the session best, in seconds."""
        best = self.best_at(code, t)
        session_best = self.session_best_at(t)
        if best is None or session_best is None:
            return None
        return best - session_best

    def laps_completed(self, code: str, t: float) -> int:
        """How many laps a driver has completed by ``t``, deleted ones included."""
        return bisect.bisect_right(self._lap_ends.get(code, []), t)

    def order_at(self, t: float) -> List[str]:
        """Driver codes ordered as the timing screen would show them.

        Drivers who have set a time come first, quickest to slowest. The rest
        follow in the order they were given.
        """
        def sort_key(code):
            best = self.best_at(code, t)
            return (best is None, best if best is not None else 0.0,
                    self._rank[code])

        return sorted(self._codes, key=sort_key)

    def positions_at(self, t: float) -> Dict[str, int]:
        """One-based position per driver, covering every driver in the session."""
        return {code: index + 1
                for index, code in enumerate(self.order_at(t))}

    def best_series(self, code: str, timeline: Sequence[float]) -> np.ndarray:
        """A driver's best lap at every point on ``timeline``.

        Frames are built one per timeline entry, so this does in one pass what
        :meth:`best_at` does one point at a time. Times before their first lap
        come back as NaN.
        """
        times = self._improve_at.get(code, [])
        values = self._improve_to.get(code, [])
        series = np.full(len(timeline), np.nan, dtype=float)
        if not times:
            return series

        index = np.searchsorted(np.asarray(times, dtype=float),
                                np.asarray(timeline, dtype=float),
                                side="right") - 1
        known = index >= 0
        series[known] = np.asarray(values, dtype=float)[index[known]]
        return series


def _seconds(value) -> Optional[float]:
    """Seconds from a pandas Timedelta, or ``None`` if there is no value."""
    if value is None:
        return None
    try:
        seconds = float(value.total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None
    return None if seconds != seconds else seconds


def read_laps(session, time_offset_s: float = 0.0) -> List[CompletedLap]:
    """Extract completed laps from a loaded session.

    Args:
        session: A loaded FastF1 session.
        time_offset_s: Value subtracted from session times to convert them to
            replay frame times, which start at zero.

    Returns:
        Every lap that has both a time and an end time. Rows that cannot be
        read are skipped rather than raising, because a session is still worth
        watching without one lap.
    """
    laps = getattr(session, "laps", None)
    if laps is None or getattr(laps, "empty", True):
        return []

    completed: List[CompletedLap] = []
    for _, row in laps.iterrows():
        try:
            code = str(row.get("Driver") or "")
            lap_time_s = _seconds(row.get("LapTime"))
            end_time_s = _seconds(row.get("Time"))
            if not code or lap_time_s is None or end_time_s is None:
                continue
            completed.append(CompletedLap(
                code=code,
                lap_number=int(row.get("LapNumber") or 0),
                lap_time_s=lap_time_s,
                end_time_s=end_time_s - float(time_offset_s),
                deleted=bool(row.get("Deleted")),
            ))
        except (AttributeError, TypeError, ValueError):
            continue
    return completed


def time_remaining(t: float, session_length_s: float) -> float:
    """How much of the session is left at ``t``, never below zero."""
    return max(0.0, float(session_length_s) - float(t))
