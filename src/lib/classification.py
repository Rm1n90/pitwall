"""Race classification: working out who is where, and in what order.

The obvious way to order a field is to project each car's ``(x, y)`` onto the
track and sort by how far round it is. That does not work with F1's data. The
position channel regularly goes stale, repeating the same coordinates for over
a second while the car is demonstrably still moving, and it occasionally jumps
hundreds of metres. Ordering on it produces a leaderboard that reshuffles
several times a lap.

The speed-integrated distance channel is far more reliable, so race progress is
built from that instead:

    progress = (lap - 1) + fraction_of_current_lap

measured in laps. The fraction is per-lap normalised, which also means a lap
driven partly down the pit lane still counts as exactly one lap, so pit stops
no longer distort the order.

Two special cases need the official timing data:

* **the start**, where every car's lap-one distance begins at zero even though
  the grid is spread over 150 metres of track, and
* **the finish**, where cars keep circulating on their cool-down lap; without a
  freeze their lap fraction wraps and the classification scrambles.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Distance between grid slots in Formula 1, in metres.
GRID_SLOT_SPACING_M = 8.0

# Position used for cars with no starting slot (pit lane start, or missing
# data). Far enough back that they never outrank a car that did start.
UNKNOWN_GRID_POSITION = 30


@dataclass(frozen=True)
class DriverClassification:
    """Official timing facts about one driver's race.

    Attributes:
        code: Three letter driver code.
        grid_position: Starting slot, 1 for pole.
        final_position: Official classified position.
        finish_time_s: Replay time at which this driver last crossed the line.
        took_flag: Whether the driver was classified as finishing. Retired
            cars have a final position too, so this is what distinguishes
            "finished 19th" from "retired on lap 14".
    """

    code: str
    grid_position: int = UNKNOWN_GRID_POSITION
    final_position: Optional[int] = None
    finish_time_s: Optional[float] = None
    took_flag: bool = False


@dataclass(frozen=True)
class RaceClassification:
    """Official classification for the whole field.

    Attributes:
        drivers: Per-driver timing facts.
        finish_time_s: Replay time at which the winner took the chequered
            flag, after which the result is settled. ``None`` if unknown.
    """

    drivers: Dict[str, DriverClassification]
    finish_time_s: Optional[float] = None

    def get(self, code: str) -> Optional[DriverClassification]:
        return self.drivers.get(code)

    def is_settled(self, t: float) -> bool:
        """True once the winner has taken the flag and the result is fixed."""
        return self.finish_time_s is not None and t >= self.finish_time_s


def lap_one_progress(rel_dist: float, grid_position: int,
                     lap_length_m: float,
                     slot_spacing_m: float = GRID_SLOT_SPACING_M) -> float:
    """Return race progress during lap one, accounting for the grid.

    Every driver's lap-one distance starts at zero, but they do not start
    level: the car in slot ``n`` sits ``(n - 1) * 8`` metres further back and
    therefore covers that much more ground to complete the lap. Without this
    correction the entire field is tied at lights out and the order at the
    first corner is decided by rounding.

    Args:
        rel_dist: Fraction of lap one completed, 0.0 to 1.0.
        grid_position: Starting slot, 1 for pole.
        lap_length_m: Length of one lap in metres.
        slot_spacing_m: Distance between grid slots.

    Returns:
        Progress in laps. Negative at lights out for everyone behind pole,
        reaching exactly 1.0 as the driver crosses the line.
    """
    if lap_length_m <= 0:
        return float(rel_dist)

    offset_m = max(0, int(grid_position) - 1) * slot_spacing_m
    # The driver covers (lap_length + offset) metres in total, starting
    # offset metres before the timing line.
    travelled_m = float(rel_dist) * (lap_length_m + offset_m)
    return (travelled_m - offset_m) / lap_length_m


def race_progress(lap: int, rel_dist: float, grid_position: int,
                  lap_length_m: float) -> float:
    """Return a driver's race progress in laps.

    Args:
        lap: Current lap number, starting at 1.
        rel_dist: Fraction of the current lap completed, 0.0 to 1.0.
        grid_position: Starting slot, used only on lap one.
        lap_length_m: Length of one lap in metres.
    """
    lap = max(1, int(lap))
    if lap == 1:
        return lap_one_progress(rel_dist, grid_position, lap_length_m)
    return (lap - 1) + float(rel_dist)


def enforce_monotonic(values: Sequence[float]) -> List[float]:
    """Return ``values`` with any backwards steps removed.

    Progress can only increase. Resampling occasionally produces a tiny dip
    where a lap boundary and the distance channel disagree by a frame; this
    clamps those out so the leaderboard never flickers.
    """
    result: List[float] = []
    highest = float("-inf")
    for value in values:
        highest = value if value > highest else highest
        result.append(highest)
    return result


def read_classification(session, time_offset_s: float = 0.0
                        ) -> RaceClassification:
    """Extract grid, finishing order and finish times from a loaded session.

    Args:
        session: A loaded FastF1 session.
        time_offset_s: Value subtracted from session times to convert them to
            replay frame times (the replay timeline starts at zero).

    Returns:
        A :class:`RaceClassification`. Missing or malformed entries are
        skipped rather than raising, because a replay is still worth watching
        without a perfect classification.
    """
    import pandas as pd

    grid: Dict[str, int] = {}
    final: Dict[str, int] = {}
    flagged: Dict[str, bool] = {}

    results = getattr(session, "results", None)
    if results is not None and not results.empty:
        for _, row in results.iterrows():
            code = str(row.get("Abbreviation") or "")
            if not code:
                continue
            try:
                slot = int(row.get("GridPosition"))
                grid[code] = slot if slot > 0 else UNKNOWN_GRID_POSITION
            except (TypeError, ValueError):
                grid[code] = UNKNOWN_GRID_POSITION
            try:
                final[code] = int(row.get("Position"))
            except (TypeError, ValueError):
                pass
            # A retired car still gets a classified position, but its
            # ClassifiedPosition is a letter ('R', 'D', 'W') rather than a
            # number. Only numbered entries actually took the flag.
            flagged[code] = str(row.get("ClassifiedPosition") or "").strip().isdigit()

    finish: Dict[str, float] = {}
    laps = getattr(session, "laps", None)
    if laps is not None and not laps.empty:
        last_lap: Dict[str, int] = {}
        for _, lap in laps.iterrows():
            code = str(lap.get("Driver") or "")
            number = lap.get("LapNumber")
            if not code or pd.isna(number):
                continue
            number = int(number)
            if number >= last_lap.get(code, 0):
                last_lap[code] = number
                end = lap.get("Time")
                if end is not None and not pd.isna(end):
                    finish[code] = end.total_seconds() - time_offset_s

    codes = set(grid) | set(final) | set(finish)
    drivers = {
        code: DriverClassification(
            code=code,
            grid_position=grid.get(code, UNKNOWN_GRID_POSITION),
            final_position=final.get(code),
            finish_time_s=finish.get(code),
            took_flag=flagged.get(code, False),
        )
        for code in codes
    }

    # The result is settled the moment the winner crosses the line.
    winner = next(
        (d for d in drivers.values()
         if d.final_position == 1 and d.took_flag), None
    )
    return RaceClassification(
        drivers=drivers,
        finish_time_s=winner.finish_time_s if winner else None,
    )


def order_drivers(entries: Iterable[Tuple[str, float]], t: float,
                  classification: RaceClassification) -> List[str]:
    """Return driver codes ordered from first to last.

    While the race is running the field is ranked purely by race progress, so
    retired cars sink down the order as everyone else drives past them.

    Once the winner takes the chequered flag the result is settled, so the
    official classification takes over. Without that, cars still completing
    their cool-down lap keep accumulating lap fraction and shuffle the final
    order.

    Args:
        entries: ``(code, progress_in_laps)`` pairs.
        t: Current replay time in seconds.
        classification: Official timing facts.
    """
    entries = list(entries)

    if not classification.is_settled(t):
        return [code for code, _ in sorted(entries, key=lambda e: -e[1])]

    classified: List[Tuple[int, str]] = []
    unclassified: List[Tuple[float, str]] = []
    for code, progress in entries:
        info = classification.get(code)
        if info is not None and info.final_position is not None:
            classified.append((info.final_position, code))
        else:
            unclassified.append((progress, code))

    classified.sort()
    unclassified.sort(key=lambda item: -item[0])
    return [code for _, code in classified] + [code for _, code in unclassified]


def assign_positions(entries: Iterable[Tuple[str, float]], t: float,
                     classification: RaceClassification) -> Dict[str, int]:
    """Return ``{code: position}`` with positions numbered from one."""
    return {
        code: index + 1
        for index, code in enumerate(order_drivers(entries, t, classification))
    }
