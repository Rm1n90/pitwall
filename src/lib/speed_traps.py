"""Speed trap readings.

F1 times every car at four points on a lap: two intermediate points, the
finish line, and the speed trap itself. The timing screens show who is fastest
at each, which is how you spot a car running less wing or towing down a
straight.
"""

import bisect
from dataclasses import dataclass
from typing import Dict, List, Sequence

# The four measured points, in the order timing screens show them.
TRAP_KEYS = ("i1", "i2", "fl", "st")
TRAP_LABELS = {"i1": "I1", "i2": "I2", "fl": "FL", "st": "TRAP"}

# Column each reading comes from in a completed session.
LAP_COLUMNS = {"i1": "SpeedI1", "i2": "SpeedI2",
               "fl": "SpeedFL", "st": "SpeedST"}


@dataclass(frozen=True)
class TrapReading:
    """A driver's best speed at one measuring point.

    Attributes:
        speed: Best speed recorded, in km/h.
        is_session_best: Whether nobody has gone faster there.
    """

    speed: float
    is_session_best: bool = False


class SpeedTraps:
    """Best speeds at each measuring point, queryable at any point in time.

    Args:
        readings: ``{code: [(replay_time, {trap: speed}), ...]}``.
    """

    def __init__(self, readings: Dict[str, Sequence]):
        self._times: Dict[str, List[float]] = {}
        self._bests: Dict[str, List[Dict[str, float]]] = {}

        for code, entries in (readings or {}).items():
            usable = sorted((float(t), values) for t, values in entries
                            if t is not None)
            if not usable:
                continue

            times, running = [], []
            best: Dict[str, float] = {}
            for moment, values in usable:
                for trap, speed in values.items():
                    if speed is None or speed <= 0:
                        continue
                    if speed > best.get(trap, 0.0):
                        best[trap] = float(speed)
                times.append(moment)
                running.append(dict(best))
            self._times[code] = times
            self._bests[code] = running

    @property
    def drivers(self) -> List[str]:
        return list(self._times)

    def best_for(self, code: str, t: float) -> Dict[str, float]:
        """Return the driver's best speed at each point, as at ``t``."""
        times = self._times.get(code)
        if not times:
            return {}
        index = bisect.bisect_right(times, t)
        if index == 0:
            return {}
        return self._bests[code][index - 1]

    def session_best(self, t: float) -> Dict[str, float]:
        """Return the fastest speed anyone has managed at each point."""
        overall: Dict[str, float] = {}
        for code in self._times:
            for trap, speed in self.best_for(code, t).items():
                if speed > overall.get(trap, 0.0):
                    overall[trap] = speed
        return overall

    def snapshot(self, code: str, t: float) -> Dict[str, TrapReading]:
        """Return a driver's readings, flagged where they lead the session."""
        overall = self.session_best(t)
        return {
            trap: TrapReading(
                speed=speed,
                is_session_best=speed >= overall.get(trap, 0.0),
            )
            for trap, speed in self.best_for(code, t).items()
        }


def from_lap_times(lap_times: Dict[str, Sequence[dict]]) -> SpeedTraps:
    """Build an index from the replay's lap entries."""
    readings: Dict[str, list] = {}
    for code, laps in (lap_times or {}).items():
        for lap in laps:
            moment = lap.get("replay_end_time_s")
            if moment is None:
                continue
            values = {}
            for trap in TRAP_KEYS:
                speed = lap.get(f"speed_{trap}")
                if speed is not None:
                    values[trap] = speed
            if values:
                readings.setdefault(code, []).append((moment, values))
    return SpeedTraps(readings)
