"""Which stretch of track is under a flag.

Race control does not just say "yellow"; it names the marshalling sector, and
says when that sector is clear again. Combined with the sector positions the
circuit publishes, that is enough to light up the actual corner where the
incident is rather than tinting the whole lap.
"""

from typing import Dict, List, Optional, Sequence, Tuple

# Flags that put a stretch of track under caution, most serious last so a
# double yellow is not overwritten by a single.
CAUTION_FLAGS = ("YELLOW", "DOUBLE YELLOW")
CLEARING_FLAGS = ("CLEAR", "GREEN")

# Colours used to draw each caution.
FLAG_COLORS = {
    "YELLOW": (226, 196, 48),
    "DOUBLE YELLOW": (240, 168, 32),
}

# A caution with no clearing message is held for this long rather than for
# the rest of the session.
DEFAULT_DURATION_S = 120.0


def _sector(value) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_sector_flags(messages: Sequence[dict]) -> List[dict]:
    """Return the periods each marshalling sector spent under a flag.

    Args:
        messages: Race control messages, each with ``time``, ``flag`` and
            ``sector``, as carried in the replay frames.

    Returns:
        Entries of ``{"sector", "flag", "start", "end"}`` in replay seconds.
        ``end`` is ``None`` for a caution that was never cleared.
    """
    periods: List[dict] = []
    open_by_sector: Dict[int, dict] = {}

    for message in sorted(messages or [], key=lambda m: m.get("time") or 0.0):
        sector = _sector(message.get("sector"))
        if sector is None:
            continue
        flag = str(message.get("flag") or "").strip().upper()
        moment = float(message.get("time") or 0.0)

        if flag in CAUTION_FLAGS:
            existing = open_by_sector.get(sector)
            if existing is not None:
                # An upgrade to double yellow replaces the single.
                if CAUTION_FLAGS.index(flag) > CAUTION_FLAGS.index(
                        existing["flag"]):
                    existing["flag"] = flag
                continue
            entry = {"sector": sector, "flag": flag,
                     "start": moment, "end": None}
            open_by_sector[sector] = entry
            periods.append(entry)
        elif flag in CLEARING_FLAGS:
            entry = open_by_sector.pop(sector, None)
            if entry is not None:
                entry["end"] = moment

    for entry in periods:
        if entry["end"] is None:
            entry["end"] = entry["start"] + DEFAULT_DURATION_S
    return periods


def active_flags(periods: Sequence[dict], t: float) -> List[dict]:
    """Return the cautions in force at replay time ``t``."""
    return [entry for entry in periods
            if entry["start"] <= t <= (entry["end"] if entry["end"]
                                       is not None else float("inf"))]


def marshal_sectors_from_circuit_info(circuit_info) -> List[Tuple[int, float, float]]:
    """Return ``(number, x, y)`` for each marshalling sector.

    Returns an empty list when the circuit information is unavailable, so
    callers need no special case.
    """
    sectors = getattr(circuit_info, "marshal_sectors", None)
    if sectors is None or len(sectors) == 0:
        return []

    result = []
    for _, row in sectors.iterrows():
        number = _sector(row.get("Number"))
        if number is None:
            continue
        try:
            result.append((number, float(row["X"]), float(row["Y"])))
        except (KeyError, TypeError, ValueError):
            continue
    result.sort()
    return result
