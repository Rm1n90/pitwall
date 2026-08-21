"""Parse the official MotoGP Analysis PDF into per-rider, per-lap timing.

The Analysis sheet is the richest public MotoGP data: for every rider, every
lap, it lists the lap time, the four intermediate splits (T1-T4), the speed
trap and the tyre compounds. There is no positional feed, so these splits are
what a replay reconstructs a bike's track position from.

Layout
------
Each page holds two half-width panels side by side. Riders flow newspaper
column-major: down the left panel, then down the right panel, continuing across
the column break and across pages. A rider's laps are therefore one contiguous,
increasing run of lap numbers in that reading order, which is what segments the
stream into riders. A name/number header is printed at the start of each run
and labels it.

Every field is copyright Dorna. This module parses a locally supplied file; it
does not fetch or redistribute the sheets.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Half-page split. Pages are 595pt wide; the left panel's lap times sit near
# x=59, the right panel's near x=331.
_HALF_X = 290

# Column centres within a panel, as (name, x) pairs. A token in a lap row is
# assigned to the nearest centre in its own half.
_LEFT_COLUMNS = (("lap", 40), ("time", 59), ("t1", 111), ("t2", 151),
                 ("t3", 187), ("t4", 227), ("speed", 264))
_RIGHT_COLUMNS = (("lap", 313), ("time", 331), ("t1", 384), ("t2", 423),
                  ("t3", 459), ("t4", 499), ("speed", 537))

_LAPTIME = re.compile(r"^(\d+)'(\d\d)\.(\d\d\d)$")
_POSITION = re.compile(r"^\d+(st|nd|rd|th)$")
_CONSTRUCTORS = {
    "DUCATI", "APRILIA", "KTM", "YAMAHA", "HONDA", "BMW", "KALEX", "TRIUMPH",
    "GASGAS", "HUSQVARNA", "CFMOTO", "FANTIC", "BOSCHUNG", "FORWARD",
}


@dataclass(frozen=True)
class Lap:
    number: int
    lap_time_s: Optional[float]
    sectors: List[Optional[float]]
    speed_kmh: Optional[float]
    cancelled: bool = False


@dataclass
class RiderLaps:
    number: Optional[int]
    name: str
    surname: str
    constructor: Optional[str]
    nation: Optional[str]
    front_tyre: Optional[str]
    rear_tyre: Optional[str]
    laps: List[Lap] = field(default_factory=list)


@dataclass
class AnalysisSheet:
    riders: List[RiderLaps]

    def by_number(self, number: int) -> Optional[RiderLaps]:
        for rider in self.riders:
            if rider.number == number:
                return rider
        return None


def _laptime_seconds(text: str) -> Optional[float]:
    match = _LAPTIME.match(text.strip("*").strip())
    if not match:
        return None
    minutes, seconds, thousandths = match.groups()
    return int(minutes) * 60 + int(seconds) + int(thousandths) / 1000.0


def _to_float(text) -> Optional[float]:
    if text is None:
        return None
    try:
        return float(str(text).strip("*"))
    except (TypeError, ValueError):
        return None


# Words within this many points of each other vertically belong to one line.
# Rows are ~12pt apart, so 3.5 comfortably clusters a row while never merging
# two, and avoids the boundary-splitting a fixed grid causes.
_LINE_TOLERANCE = 3.5


def _group_lines(words, x_lo, x_hi):
    """Cluster a half-panel's words into lines by vertical position.

    Clustering with a tolerance, rather than rounding to a fixed grid, keeps a
    lap's number and time together even when they sit a pixel either side of a
    grid boundary.
    """
    panel = sorted((w for w in words if x_lo <= w["x0"] < x_hi),
                   key=lambda w: w["top"])
    lines = []
    for word in panel:
        if lines and word["top"] - lines[-1][0] <= _LINE_TOLERANCE:
            lines[-1][1].append(word)
        else:
            lines.append((word["top"], [word]))
    return [(top, sorted(group, key=lambda w: w["x0"])) for top, group in lines]


def _nearest_column(x, columns):
    return min(columns, key=lambda c: abs(c[1] - x))[0]


def _extract_lap(line_words, columns):
    """Return a ``Lap`` if this line carries a lap row, else ``None``.

    A lap row is identified by its columns, not by token order: the lap number
    is the integer nearest the lap column and the time is the ``m'ss.mmm`` token
    nearest the time column. This survives left-panel header text (``Valid
    laps=25``, ``New Tyre``) bleeding across the page midline into the same
    visual line as a right-panel lap.
    """
    centres = dict(columns)
    lap_x, time_x = centres["lap"], centres["time"]

    number_word = None
    for word in line_words:
        if word["text"].strip("*").isdigit():
            if number_word is None or abs(word["x0"] - lap_x) < abs(number_word["x0"] - lap_x):
                number_word = word
    time_word = None
    for word in line_words:
        if _laptime_seconds(word["text"]) is not None:
            if time_word is None or abs(word["x0"] - time_x) < abs(time_word["x0"] - time_x):
                time_word = word
    if number_word is None or time_word is None:
        return None
    # The lap number sits in the lap column and the time in the time column;
    # anything far from those centres is stray text from the other panel.
    if abs(number_word["x0"] - lap_x) > 24 or abs(time_word["x0"] - time_x) > 24:
        return None

    cells: Dict[str, str] = {}
    for word in line_words:
        column = _nearest_column(word["x0"], columns)
        if abs(word["x0"] - centres[column]) <= 24:
            cells.setdefault(column, word["text"])

    return Lap(
        number=int(number_word["text"].strip("*")),
        lap_time_s=_laptime_seconds(time_word["text"]),
        sectors=[_to_float(cells.get(k)) for k in ("t1", "t2", "t3", "t4")],
        speed_kmh=_to_float(cells.get("speed", "")),
        cancelled="*" in number_word["text"] or "*" in time_word["text"],
    )


def _header_at(line_words):
    """If this line names a rider, return ``(name, surname, constructor, nation)``."""
    texts = [w["text"] for w in line_words]
    for i, token in enumerate(texts):
        if token in _CONSTRUCTORS and i >= 1 and i + 1 < len(texts):
            nation = texts[i + 1] if re.match(r"^[A-Z]{3}$", texts[i + 1]) else None
            surname = texts[i - 1]
            name = " ".join(texts[:i - 1]) if i >= 2 else ""
            return name, surname, token, nation
    return None


def _tyres_at(line_words):
    """If this line carries the tyre header, return ``(front, rear)``."""
    texts = [w["text"] for w in line_words]
    if "Front" in texts and "Rear" in texts and "Tyre" in texts:
        joined = " ".join(texts)
        front = re.search(r"Front Tyre (\S+)", joined)
        rear = re.search(r"Rear Tyre (\S+)", joined)
        return (front.group(1) if front else None,
                rear.group(1) if rear else None)
    return None


def _number_at(line_words):
    """If this line starts with a position token, return the rider number."""
    texts = [w["text"] for w in line_words]
    for i, token in enumerate(texts[:-1]):
        if _POSITION.match(token) and texts[i + 1].isdigit():
            return int(texts[i + 1])
    return None


def parse_analysis(path: str) -> AnalysisSheet:
    """Parse an Analysis PDF at ``path`` into an :class:`AnalysisSheet`."""
    import pdfplumber

    # A rider is a contiguous run of increasing lap numbers in reading order.
    # Header text encountered while a run is open is attached to the run it
    # opens, keyed by the run's first lap so it can be matched up afterwards.
    runs: List[dict] = []
    current: Optional[dict] = None
    pending_header: dict = {}

    def close_run():
        nonlocal current
        if current and current["laps"]:
            runs.append(current)
        current = None

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            for x_lo, x_hi, columns in (
                (0, _HALF_X, _LEFT_COLUMNS),
                (_HALF_X, page.width, _RIGHT_COLUMNS),
            ):
                for _key, line_words in _group_lines(words, x_lo, x_hi):
                    number = _number_at(line_words)
                    if number is not None:
                        pending_header["number"] = number
                    header = _header_at(line_words)
                    if header:
                        pending_header.update(
                            name=header[0], surname=header[1],
                            constructor=header[2], nation=header[3])
                    tyres = _tyres_at(line_words)
                    if tyres:
                        pending_header["front_tyre"] = tyres[0]
                        pending_header["rear_tyre"] = tyres[1]

                    lap = _extract_lap(line_words, columns)
                    if lap is None:
                        continue
                    # A lap number that does not advance the current run opens
                    # a new rider.
                    if current is None or lap.number <= current["last"]:
                        close_run()
                        current = {"laps": [], "last": 0,
                                   "header": dict(pending_header)}
                        pending_header = {}
                    current["laps"].append(lap)
                    current["last"] = lap.number
        close_run()

    riders = []
    for run in runs:
        head = run["header"]
        riders.append(RiderLaps(
            number=head.get("number"),
            name=head.get("name", ""),
            surname=head.get("surname", ""),
            constructor=head.get("constructor"),
            nation=head.get("nation"),
            front_tyre=head.get("front_tyre"),
            rear_tyre=head.get("rear_tyre"),
            laps=run["laps"],
        ))
    return AnalysisSheet(riders=riders)
