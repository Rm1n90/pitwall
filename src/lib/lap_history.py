"""Lap times as they stood at any point in a session.

The timing tower needs to know, for the moment being replayed, each driver's
most recent lap, their own best so far, and the best anyone had set. Scanning
the whole session for that on every frame would be wasteful, so the laps are
indexed once and looked up by time.
"""

import bisect
from typing import Dict, List, Optional, Sequence, Tuple

# How a sector time compares with the rest of the session.
SECTOR_NORMAL = 0
SECTOR_PERSONAL_BEST = 1
SECTOR_OVERALL_BEST = 2


def _sector_times(lap: dict) -> List[Optional[float]]:
    """Return the three sector times from a lap entry, where present."""
    times = []
    for key in ("sector1_s", "sector2_s", "sector3_s"):
        value = lap.get(key)
        try:
            times.append(float(value) if value is not None else None)
        except (TypeError, ValueError):
            times.append(None)
    return times


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
        #: ``{code: [[status, status, status], ...]}`` per completed lap.
        self._sectors: Dict[str, List[List[int]]] = {}
        #: ``{code: [bool, ...]}`` whether each lap was taken away.
        self._deleted: Dict[str, List[bool]] = {}

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
                usable.append((float(end), float(seconds),
                               _sector_times(lap), bool(lap.get("deleted"))))
            if not usable:
                continue
            usable.sort()

            ends, times, bests = [], [], []
            best = None
            for end, seconds, _, deleted in usable:
                # A deleted lap still put mileage on the car, so it stays in
                # the history, but it can never stand as anybody's best.
                if not deleted and (best is None or seconds < best):
                    best = seconds
                ends.append(end)
                times.append(seconds)
                bests.append(best)
            self._ends[code] = ends
            self._times[code] = times
            self._bests[code] = bests
            self._sectors[code] = [sectors for _, _, sectors, _ in usable]
            self._deleted[code] = [deleted for _, _, _, deleted in usable]

        self._grade_sectors()

    def _grade_sectors(self) -> None:
        """Work out which sector times were personal or overall bests.

        Laps are graded in the order they were set across the whole field, so
        a purple sector is purple only until somebody beats it.
        """
        ordered = []
        for code, ends in self._ends.items():
            for index, end in enumerate(ends):
                ordered.append((end, code, index))
        ordered.sort()

        personal: Dict[str, List[Optional[float]]] = {}
        overall: List[Optional[float]] = [None, None, None]
        graded: Dict[str, List[List[int]]] = {
            code: [[SECTOR_NORMAL] * 3 for _ in laps]
            for code, laps in self._sectors.items()
        }

        for _, code, index in ordered:
            if self._deleted.get(code, [])[index:index + 1] == [True]:
                # The sectors of a lap that was taken away do not count.
                continue
            times = self._sectors[code][index]
            bests = personal.setdefault(code, [None, None, None])
            for sector, seconds in enumerate(times):
                if seconds is None or seconds <= 0:
                    continue
                if overall[sector] is None or seconds < overall[sector]:
                    overall[sector] = seconds
                    bests[sector] = seconds
                    graded[code][index][sector] = SECTOR_OVERALL_BEST
                elif bests[sector] is None or seconds < bests[sector]:
                    bests[sector] = seconds
                    graded[code][index][sector] = SECTOR_PERSONAL_BEST

        self._sectors = graded

    def sector_status(self, code: str, t: float) -> List[int]:
        """Return the status of the driver's three most recent sectors."""
        index = self._index_at(code, t)
        laps = self._sectors.get(code)
        if not laps or index == 0:
            return [SECTOR_NORMAL] * 3
        return laps[index - 1]

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
            "sectors": {code: self.sector_status(code, t)
                        for code in self._ends},
        }
