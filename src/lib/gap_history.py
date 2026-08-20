"""How far each driver was from the lead, lap by lap.

A gap chart shows a race the way the pit wall reads it: not who is where, but
how much time is between them, and whether that time is coming down. The two
sources differ. Offline the lap table says exactly when every car crossed the
line, so a gap is a subtraction. Live there is no lap table, so the gap is
read off the timing feed, which writes it as a string.
"""

import re
from typing import Dict, List, Optional, Sequence, Tuple

# The feed writes a gap in seconds, but switches to whole laps once a car is
# lapped, and uses a placeholder before the race is running.
_SECONDS = re.compile(r"^\+?(\d+(?:\.\d+)?)$")

GapHistory = Dict[str, List[Tuple[int, float]]]


def parse_gap(value) -> Optional[float]:
    """Read a gap in seconds from the feed's string, if that is what it is.

    Returns ``None`` for a lapped car, for the leader's empty string, and for
    anything unrecognised. A lap is not a number of seconds, so a lapped car
    has no gap this chart can draw.
    """
    if not isinstance(value, str):
        return None
    match = _SECONDS.match(value.strip())
    return float(match.group(1)) if match else None


def _crossings(laps: Sequence[dict]) -> Dict[int, float]:
    """When this driver crossed the line to complete each lap."""
    crossings = {}
    for lap in laps or ():
        end = lap.get("replay_end_time_s")
        if end is None:
            end = lap.get("replay_line_time_s")
        number = lap.get("lap")
        if end is None or number is None:
            continue
        try:
            crossings[int(number)] = float(end)
        except (TypeError, ValueError):
            continue
    return crossings


def from_lap_times(lap_times: Optional[Dict[str, Sequence[dict]]]) -> GapHistory:
    """Build the gap history from a finished session's lap table.

    The gap on a lap is measured against whoever crossed the line first on
    that lap, so a change of lead moves the reference with it.
    """
    crossings = {code: _crossings(laps)
                 for code, laps in (lap_times or {}).items()}
    crossings = {code: laps for code, laps in crossings.items() if laps}
    if not crossings:
        return {}

    leader_at: Dict[int, float] = {}
    for laps in crossings.values():
        for number, end in laps.items():
            if number not in leader_at or end < leader_at[number]:
                leader_at[number] = end

    history: GapHistory = {}
    for code, laps in crossings.items():
        entries = [(number, round(end - leader_at[number], 3))
                   for number, end in sorted(laps.items())]
        if entries:
            history[code] = entries
    return history


def update_from_frame(history: GapHistory, frame: dict) -> None:
    """Record the gaps in one live frame, in place.

    Only the first frame of each of a driver's laps is kept, so the chart
    gets one point per lap rather than one per frame.
    """
    for code, car in (frame.get("drivers") or {}).items():
        try:
            lap = int(car.get("lap") or 0)
        except (TypeError, ValueError):
            continue
        if lap <= 0:
            continue

        entries = history.get(code)
        if entries and entries[-1][0] >= lap:
            continue

        raw = car.get("gap_to_leader")
        if raw == "":
            gap = 0.0  # The leader's own gap is empty rather than zero.
        else:
            gap = parse_gap(raw)
        if gap is None:
            continue

        history.setdefault(code, []).append((lap, gap))


def merge(base: GapHistory, incoming: GapHistory) -> GapHistory:
    """Fold ``incoming`` into ``base``, keeping whichever history is longer."""
    for code, entries in (incoming or {}).items():
        if len(entries) >= len(base.get(code, ())):
            base[code] = list(entries)
    return base


def to_payload(history: GapHistory) -> Dict[str, list]:
    """Convert to something that survives the JSON telemetry stream."""
    return {code: [[int(lap), float(gap)] for lap, gap in entries]
            for code, entries in (history or {}).items()}
