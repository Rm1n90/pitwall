"""Typed views over the MotoGP pulselive JSON.

Parsing is kept separate from fetching so the whole data layer can be tested
against recorded fixtures without touching the network. Every ``parse_*``
function takes the decoded JSON exactly as the API returns it and returns
immutable dataclasses.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


def _clean_category(name: str) -> str:
    """Strip the trademark glyph so ``MotoGP™`` matches ``MotoGP``."""
    return (name or "").replace("™", "").strip()


def _gap_seconds(value) -> Optional[float]:
    """Parse a gap string such as ``"1.407"`` into seconds.

    Gaps expressed in laps (``"1 Lap"``) or missing entirely come back as
    ``None`` rather than a misleading number.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or "lap" in text.lower():
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class Season:
    id: str
    year: int
    current: bool


@dataclass(frozen=True)
class Circuit:
    id: Optional[str]
    name: Optional[str]
    legacy_id: Optional[int]
    place: Optional[str]


@dataclass(frozen=True)
class Event:
    id: str
    short_name: Optional[str]
    name: Optional[str]
    sponsored_name: Optional[str]
    circuit: Circuit
    country_iso: Optional[str]
    test: bool


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    legacy_id: Optional[int]


@dataclass(frozen=True)
class SessionRef:
    id: str
    type: str
    number: Optional[int]
    code: str
    date: Optional[str]
    condition: Dict[str, str]
    files: Dict[str, str]

    def _file(self, key: str) -> Optional[str]:
        url = self.files.get(key)
        return url or None

    @property
    def analysis_url(self) -> Optional[str]:
        return self._file("analysis")

    @property
    def lap_chart_url(self) -> Optional[str]:
        return self._file("lap_chart")

    @property
    def classification_url(self) -> Optional[str]:
        return self._file("classification")

    @property
    def grid_url(self) -> Optional[str]:
        return self._file("grid")


@dataclass(frozen=True)
class ClassificationRow:
    position: Optional[int]
    rider_name: str
    rider_number: Optional[int]
    rider_id: Optional[str]
    rider_legacy_id: Optional[int]
    team_name: Optional[str]
    constructor_name: Optional[str]
    average_speed: Optional[float]
    gap_first: Optional[float]
    total_laps: Optional[int]
    time: Optional[str]
    points: Optional[int]
    status: Optional[str]


@dataclass(frozen=True)
class Rider:
    legacy_id: Optional[int]
    name: str
    surname: str
    number: Optional[int]
    nation_iso: Optional[str]
    team_name: Optional[str]
    color: Optional[str]
    text_color: Optional[str]
    portrait_url: Optional[str]


@dataclass(frozen=True)
class LiveRider:
    order: int
    pos: int
    number: Optional[int]
    name: Optional[str]
    surname: Optional[str]
    shortname: Optional[str]
    nation: Optional[str]
    color: Optional[str]
    text_color: Optional[str]
    lap_time: Optional[str]
    num_lap: Optional[int]
    last_lap_time: Optional[str]
    last_lap: Optional[int]
    gap_first: Optional[float]
    gap_prev: Optional[float]
    on_pit: bool
    status_id: Optional[str]
    status_name: Optional[str]
    trac_status: Optional[str]
    team_name: Optional[str]
    bike_name: Optional[str]


@dataclass(frozen=True)
class LiveTiming:
    category: Optional[str]
    circuit_name: Optional[str]
    event_name: Optional[str]
    session_type: Optional[int]
    session_name: Optional[str]
    session_shortname: Optional[str]
    session_status_id: Optional[str]
    num_laps: Optional[int]
    remaining: Optional[str]
    riders: List[LiveRider]
    head: Dict


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_seasons(payload) -> List[Season]:
    return [
        Season(id=s["id"], year=int(s["year"]), current=bool(s.get("current")))
        for s in payload
    ]


def _parse_circuit(payload) -> Circuit:
    payload = payload or {}
    return Circuit(
        id=payload.get("id"),
        name=payload.get("name"),
        legacy_id=payload.get("legacy_id"),
        place=payload.get("place"),
    )


def parse_events(payload) -> List[Event]:
    events = []
    for e in payload:
        country = e.get("country") or {}
        events.append(Event(
            id=e["id"],
            short_name=e.get("short_name"),
            name=e.get("name"),
            sponsored_name=e.get("sponsored_name"),
            circuit=_parse_circuit(e.get("circuit")),
            country_iso=country.get("iso"),
            test=bool(e.get("test")),
        ))
    return events


def parse_categories(payload) -> List[Category]:
    return [
        Category(id=c["id"], name=_clean_category(c.get("name")),
                 legacy_id=c.get("legacy_id"))
        for c in payload
    ]


def _session_code(session_type: str, number: Optional[int]) -> str:
    """Fold a type and number into a stable code, e.g. ``FP`` + ``1`` -> ``FP1``."""
    if number:
        return f"{session_type}{number}"
    return session_type


def _session_files(payload) -> Dict[str, str]:
    files = {}
    for key, entry in (payload.get("session_files") or {}).items():
        url = (entry or {}).get("url")
        if url:
            files[key] = url
    return files


def parse_sessions(payload) -> List[SessionRef]:
    sessions = []
    for s in payload:
        stype = s.get("type")
        number = s.get("number")
        sessions.append(SessionRef(
            id=s["id"],
            type=stype,
            number=number,
            code=_session_code(stype, number),
            date=s.get("date"),
            condition=s.get("condition") or {},
            files=_session_files(s),
        ))
    return sessions


def parse_classification(payload) -> List[ClassificationRow]:
    rows = []
    for row in payload.get("classification", []):
        rider = row.get("rider") or {}
        team = row.get("team") or {}
        constructor = row.get("constructor") or {}
        gap = row.get("gap") or {}
        rows.append(ClassificationRow(
            position=row.get("position"),
            rider_name=rider.get("full_name"),
            rider_number=_as_int(rider.get("number")),
            rider_id=rider.get("id"),
            rider_legacy_id=rider.get("legacy_id"),
            team_name=team.get("name"),
            constructor_name=constructor.get("name"),
            average_speed=_as_float(row.get("average_speed")),
            gap_first=_gap_seconds(gap.get("first")),
            total_laps=_as_int(row.get("total_laps")),
            time=row.get("time"),
            points=_as_int(row.get("points")),
            status=row.get("status"),
        ))
    rows.sort(key=lambda r: (r.position is None, r.position or 0))
    return rows


def parse_riders(payload) -> List[Rider]:
    riders = []
    for r in payload:
        step = r.get("current_career_step") or {}
        team = step.get("team") or {}
        country = r.get("country") or {}
        pictures = step.get("pictures") or {}
        profile = (pictures.get("profile") or {})
        riders.append(Rider(
            legacy_id=r.get("legacy_id"),
            name=r.get("name"),
            surname=r.get("surname"),
            number=_as_int(step.get("number")),
            nation_iso=country.get("iso"),
            team_name=team.get("name"),
            color=team.get("color"),
            text_color=team.get("text_color"),
            portrait_url=profile.get("main"),
        ))
    return riders


def parse_livetiming(payload) -> LiveTiming:
    head = payload.get("head") or {}
    riders = []
    for entry in (payload.get("rider") or {}).values():
        riders.append(LiveRider(
            order=_as_int(entry.get("order")) or 0,
            pos=_as_int(entry.get("pos")) or 0,
            number=_as_int(entry.get("rider_number")),
            name=entry.get("rider_name"),
            surname=entry.get("rider_surname"),
            shortname=entry.get("rider_shortname"),
            nation=entry.get("rider_nation"),
            color=_as_hex(entry.get("color")),
            text_color=_as_hex(entry.get("text_color")),
            lap_time=entry.get("lap_time"),
            num_lap=_as_int(entry.get("num_lap")),
            last_lap_time=entry.get("last_lap_time"),
            last_lap=_as_int(entry.get("last_lap")),
            gap_first=_gap_seconds(entry.get("gap_first")),
            gap_prev=_gap_seconds(entry.get("gap_prev")),
            on_pit=bool(entry.get("on_pit")),
            status_id=entry.get("status_id"),
            status_name=entry.get("status_name"),
            trac_status=entry.get("trac_status"),
            team_name=entry.get("team_name"),
            bike_name=entry.get("bike_name"),
        ))
    # Riders still classified carry a positive position; DNS/DNF entries come
    # through as pos -1 and are sent to the back, ordered by feed order.
    riders.sort(key=lambda r: (r.pos <= 0, r.pos if r.pos > 0 else r.order))
    return LiveTiming(
        category=head.get("category"),
        circuit_name=head.get("circuit_name"),
        event_name=head.get("event_tv_name"),
        session_type=_as_int(head.get("session_type")),
        session_name=head.get("session_name"),
        session_shortname=head.get("session_shortname"),
        session_status_id=head.get("session_status_id"),
        num_laps=_as_int(head.get("num_laps")),
        remaining=head.get("remaining"),
        riders=riders,
        head=head,
    )


def _as_hex(value) -> Optional[str]:
    """Normalise a bare hex colour such as ``e34d1e`` to ``#e34d1e``."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if text.startswith("#") else f"#{text}"


@dataclass(frozen=True)
class LiveSessionSlot:
    code: Optional[str]
    name: Optional[str]
    category: Optional[str]
    date_start: Optional[str]
    num_laps: Optional[int]
    status: Optional[str]
    is_live: bool
    has_timing: bool


@dataclass(frozen=True)
class ScheduleEntry:
    circuit_name: Optional[str]
    circuit_svg_url: Optional[str]
    circuit_length_m: Optional[float]
    slots: List["LiveSessionSlot"]


def parse_schedule(payload) -> List[ScheduleEntry]:
    """Parse broadcast ``/events`` into circuit assets and session slots.

    The broadcast feed is the only place the circuit outline SVG and the live
    per-session status are published, so this is what drives geometry lookup
    and live-session discovery.
    """
    entries = []
    for event in payload:
        circuit = event.get("circuit") or {}
        tracks = circuit.get("tracks") or [{}]
        track = tracks[0] if tracks else {}
        info = ((track.get("assets") or {}).get("info") or {})
        slots = []
        for b in (event.get("broadcasts") or []):
            slots.append(LiveSessionSlot(
                code=b.get("shortname"),
                name=b.get("name"),
                category=b.get("category"),
                date_start=b.get("date_start"),
                num_laps=_as_int(b.get("num_laps")),
                status=b.get("status"),
                is_live=bool(b.get("is_live")),
                has_timing=bool(b.get("has_timing")),
            ))
        entries.append(ScheduleEntry(
            circuit_name=circuit.get("name"),
            circuit_svg_url=info.get("path"),
            circuit_length_m=_as_float(track.get("lenght")),
            slots=slots,
        ))
    return entries
