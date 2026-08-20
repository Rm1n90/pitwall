"""Lap times as they stood at any point in a session.

The timing tower needs to know, for the moment being replayed, each driver's
most recent lap, their own best so far, and the best anyone had set. Scanning
the whole session for that on every frame would be wasteful, so the laps are
indexed once and looked up by time.
"""

import bisect
from typing import Dict, List, Optional, Sequence, Tuple


class LapHistory:
    """Indexed lap times, queryable at any point in the session.

    Args:
        lap_times: ``{code: [{"lap", "time_s", "end_time_s"}, ...]}`` as
            produced by the replay window.
    """

    def __init__(self, lap_times: Dict[str, Sequence[dict]]):
        self._ends: Dict[str, List[float]] = {}
        self._times: Dict[str, List[float]] = {}
        self._bests: Dict[str, List[float]] = {}

        for code, laps in (lap_times or {}).items():
            usable = []
            for lap in laps:
                # Lap entries carry two clocks: `end_time_s` is session time,
                # counted from when the timing feed started, while frames are
                # replay time counted from zero. Only the replay clock can be
                # compared against a frame.
                end = lap.get("replay_end_time_s")
                if end is None:
                    end = lap.get("replay_line_time_s")
                seconds = lap.get("time_s")
                if end is None or seconds is None or seconds <= 0:
                    continue
                usable.append((float(end), float(seconds)))
            if not usable:
                continue
            usable.sort()

            ends, times, bests = [], [], []
            best = float("inf")
            for end, seconds in usable:
                best = min(best, seconds)
                ends.append(end)
                times.append(seconds)
                bests.append(best)
            self._ends[code] = ends
            self._times[code] = times
            self._bests[code] = bests

    @property
    def drivers(self) -> List[str]:
        return list(self._ends)

    def _index_at(self, code: str, t: float) -> int:
        """Return how many laps this driver had completed by ``t``."""
        ends = self._ends.get(code)
        if not ends:
            return 0
        return bisect.bisect_right(ends, t)

    def last_lap(self, code: str, t: float) -> Optional[float]:
        """Return the driver's most recently completed lap time."""
        index = self._index_at(code, t)
        if index == 0:
            return None
        return self._times[code][index - 1]

    def personal_best(self, code: str, t: float) -> Optional[float]:
        """Return the driver's best lap so far."""
        index = self._index_at(code, t)
        if index == 0:
            return None
        return self._bests[code][index - 1]

    def session_best(self, t: float) -> Tuple[Optional[float], Optional[str]]:
        """Return the best lap set by anyone so far, and who set it."""
        best: Optional[float] = None
        holder: Optional[str] = None
        for code in self._ends:
            value = self.personal_best(code, t)
            if value is not None and (best is None or value < best):
                best, holder = value, code
        return best, holder

    def snapshot(self, t: float) -> dict:
        """Return everything the timing tower needs for one frame."""
        last = {}
        bests = {}
        for code in self._ends:
            value = self.last_lap(code, t)
            if value is not None:
                last[code] = value
            personal = self.personal_best(code, t)
            if personal is not None:
                bests[code] = personal

        best = None
        holder = None
        for code, value in bests.items():
            if best is None or value < best:
                best, holder = value, code

        return {
            "last_laps": last,
            "personal_bests": bests,
            "session_best": best,
            "session_best_code": holder,
        }
