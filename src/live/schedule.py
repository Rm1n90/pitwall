"""Discovery of the session that is currently running (or about to run).

F1 publishes an index of every session of the season, including the exact
feed path used by the live timing archive:
``https://livetiming.formula1.com/static/<year>/Index.json``

That index is the authority for which session is live, so it is used directly
rather than inferring it from the FastF1 event schedule.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from src.live.decoding import parse_gmt_offset, parse_utc

INDEX_URL_TEMPLATE = "https://livetiming.formula1.com/static/{year}/Index.json"
REQUEST_TIMEOUT = 20

# A session counts as "joinable" from a little before its scheduled start
# (the feed comes alive early) until well after its scheduled end, because
# races regularly overrun after a red flag.
JOIN_WINDOW_BEFORE = timedelta(minutes=45)
JOIN_WINDOW_AFTER = timedelta(hours=3)


@dataclass(frozen=True)
class LiveSessionRef:
    """Everything needed to attach to one session's live feeds."""

    year: int
    key: int
    path: str
    session_type: str
    name: str
    meeting_name: str
    country: str
    location: str
    circuit_short_name: str
    start_utc: datetime
    end_utc: Optional[datetime]

    @property
    def title(self) -> str:
        return f"{self.meeting_name} - {self.name}"

    def is_live(self, now: Optional[datetime] = None) -> bool:
        """True when ``now`` falls inside this session's joinable window."""
        now = now or datetime.now(timezone.utc)
        if now < self.start_utc - JOIN_WINDOW_BEFORE:
            return False
        end = self.end_utc or (self.start_utc + timedelta(hours=2))
        return now <= end + JOIN_WINDOW_AFTER

    def seconds_until_start(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (self.start_utc - now).total_seconds()

    def fastf1_session_type(self) -> str:
        """Map the feed's session type onto a FastF1 identifier."""
        name = (self.name or "").lower()
        session_type = (self.session_type or "").lower()
        if "sprint" in name and "qualifying" in name:
            return "SQ"
        if "sprint" in name:
            return "S"
        if "qualifying" in session_type or "qualifying" in name:
            return "Q"
        if "practice" in session_type or "practice" in name:
            for number in ("1", "2", "3"):
                if number in name:
                    return f"FP{number}"
            return "FP1"
        return "R"


def _session_from_entry(year: int, meeting: dict, session: dict
                        ) -> Optional[LiveSessionRef]:
    path = session.get("Path")
    start_local = parse_utc(session.get("StartDate"))
    if not path or start_local is None:
        return None

    offset = parse_gmt_offset(session.get("GmtOffset"))
    end_local = parse_utc(session.get("EndDate"))
    circuit = (meeting.get("Circuit") or {})
    country = (meeting.get("Country") or {})

    return LiveSessionRef(
        year=year,
        key=int(session.get("Key") or 0),
        path=path,
        session_type=str(session.get("Type") or ""),
        name=str(session.get("Name") or session.get("Type") or ""),
        meeting_name=str(meeting.get("Name") or ""),
        country=str(country.get("Name") or ""),
        location=str(meeting.get("Location") or ""),
        circuit_short_name=str(circuit.get("ShortName") or ""),
        start_utc=start_local - offset,
        end_utc=(end_local - offset) if end_local is not None else None,
    )


def fetch_season_sessions(year: int,
                          session: Optional[requests.Session] = None
                          ) -> List[LiveSessionRef]:
    """Fetch every session of ``year`` from the live timing index.

    Raises:
        RuntimeError: if the index cannot be fetched or parsed.
    """
    http = session or requests
    url = INDEX_URL_TEMPLATE.format(year=year)
    try:
        response = http.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        # The index is served with a UTF-8 BOM that json.loads rejects.
        index = json.loads(response.content.decode("utf-8-sig"))
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"could not read the F1 session index: {exc}") from exc

    sessions = []
    for meeting in index.get("Meetings", []) or []:
        for entry in meeting.get("Sessions", []) or []:
            parsed = _session_from_entry(year, meeting, entry)
            if parsed is not None:
                sessions.append(parsed)
    sessions.sort(key=lambda item: item.start_utc)
    return sessions


def find_live_session(now: Optional[datetime] = None,
                      year: Optional[int] = None,
                      session: Optional[requests.Session] = None
                      ) -> Optional[LiveSessionRef]:
    """Return the session that is currently joinable, if any.

    When several sessions overlap the window (a sprint weekend morning, for
    example) the one that started most recently wins.
    """
    now = now or datetime.now(timezone.utc)
    year = year or now.year
    candidates = [s for s in fetch_season_sessions(year, session)
                  if s.is_live(now)]
    if not candidates:
        return None
    started = [s for s in candidates if s.start_utc <= now]
    return started[-1] if started else candidates[0]


def find_next_session(now: Optional[datetime] = None,
                      year: Optional[int] = None,
                      session: Optional[requests.Session] = None
                      ) -> Optional[LiveSessionRef]:
    """Return the next session that has not started yet."""
    now = now or datetime.now(timezone.utc)
    year = year or now.year
    upcoming = [s for s in fetch_season_sessions(year, session)
                if s.start_utc > now]
    return upcoming[0] if upcoming else None


def find_session_by_path(path: str, year: Optional[int] = None,
                         session: Optional[requests.Session] = None
                         ) -> Optional[LiveSessionRef]:
    """Look up a session by its feed path."""
    if year is None:
        try:
            year = int(str(path).split("/", 1)[0])
        except (ValueError, IndexError):
            year = datetime.now(timezone.utc).year
    wanted = path if path.endswith("/") else path + "/"
    for candidate in fetch_season_sessions(year, session):
        candidate_path = candidate.path if candidate.path.endswith("/") \
            else candidate.path + "/"
        if candidate_path == wanted:
            return candidate
    return None


def describe_wait(seconds: float) -> str:
    """Format a countdown such as ``'2h 14m'`` for the user."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def build_session_path(event_date, event_name: str,
                       session_date, session_name: str) -> str:
    """Construct the live timing feed path for a session.

    F1's index only lists a meeting once its weekend is under way, so an
    upcoming session's path has to be derived from the schedule:
    ``<year>/<event date>_<Event_Name>/<session date>_<Session_Name>/``

    Args:
        event_date: Date of the event (the race day).
        event_name: Event name, e.g. ``'Dutch Grand Prix'``.
        session_date: Date the session takes place on.
        session_name: Session name, e.g. ``'Qualifying'``.
    """
    def _slug(value: str) -> str:
        return "_".join(str(value).split())

    def _date(value) -> str:
        return value.strftime("%Y-%m-%d")

    return (
        f"{event_date.year}/{_date(event_date)}_{_slug(event_name)}/"
        f"{_date(session_date)}_{_slug(session_name)}/"
    )


def session_path_exists(path: str,
                        session: Optional[requests.Session] = None) -> bool:
    """Check whether a feed path is already published."""
    http = session or requests
    base = path if path.endswith("/") else path + "/"
    url = f"https://livetiming.formula1.com/static/{base}SessionInfo.json"
    try:
        response = http.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return False
    return response.status_code == 200


def find_scheduled_session(now: Optional[datetime] = None,
                           year: Optional[int] = None
                           ) -> Optional[LiveSessionRef]:
    """Find a joinable session using the FastF1 event schedule.

    Used when F1's own index has not published the current weekend yet, which
    is the normal state of affairs until a session actually goes live.
    Returns ``None`` when FastF1 is unavailable or nothing is close enough.
    """
    now = now or datetime.now(timezone.utc)
    year = year or now.year
    try:
        import fastf1
        import pandas as pd
    except ImportError:
        return None

    try:
        schedule = fastf1.get_event_schedule(year)
    except Exception as exc:
        print(f"[live] could not load the FastF1 schedule: {exc}")
        return None

    naive_now = now.replace(tzinfo=None)
    best = None
    for _, event in schedule.iterrows():
        try:
            if event.is_testing():
                continue
        except Exception:
            pass
        for index in range(1, 6):
            name = event.get(f"Session{index}")
            start = event.get(f"Session{index}DateUtc")
            if not name or start is None or pd.isna(start):
                continue
            start = start.to_pydatetime()
            if not (start - JOIN_WINDOW_BEFORE <= naive_now
                    <= start + JOIN_WINDOW_AFTER):
                continue
            candidate = LiveSessionRef(
                year=year,
                key=0,
                path=build_session_path(
                    event["EventDate"], event["EventName"], start, name
                ),
                session_type=str(name),
                name=str(name),
                meeting_name=str(event["EventName"]),
                country=str(event.get("Country", "")),
                location=str(event.get("Location", "")),
                circuit_short_name=str(event.get("Location", "")),
                start_utc=start.replace(tzinfo=timezone.utc),
                end_utc=None,
            )
            if best is None or candidate.start_utc > best.start_utc:
                best = candidate
    return best


def find_next_scheduled_session(now: Optional[datetime] = None,
                                year: Optional[int] = None
                                ) -> Optional[LiveSessionRef]:
    """Return the next upcoming session according to the FastF1 schedule.

    F1's own index only lists weekends that are already under way, so the
    countdown to the next session has to come from the published calendar.
    """
    now = now or datetime.now(timezone.utc)
    year = year or now.year
    try:
        import fastf1
        import pandas as pd
    except ImportError:
        return None

    candidates = []
    for candidate_year in (year, year + 1):
        try:
            schedule = fastf1.get_event_schedule(candidate_year)
        except Exception:
            continue
        naive_now = now.replace(tzinfo=None)
        for _, event in schedule.iterrows():
            try:
                if event.is_testing():
                    continue
            except Exception:
                pass
            for index in range(1, 6):
                name = event.get(f"Session{index}")
                start = event.get(f"Session{index}DateUtc")
                if not name or start is None or pd.isna(start):
                    continue
                start = start.to_pydatetime()
                if start <= naive_now:
                    continue
                candidates.append(LiveSessionRef(
                    year=candidate_year,
                    key=0,
                    path=build_session_path(
                        event["EventDate"], event["EventName"], start, name
                    ),
                    session_type=str(name),
                    name=str(name),
                    meeting_name=str(event["EventName"]),
                    country=str(event.get("Country", "")),
                    location=str(event.get("Location", "")),
                    circuit_short_name=str(event.get("Location", "")),
                    start_utc=start.replace(tzinfo=timezone.utc),
                    end_utc=None,
                ))
        if candidates:
            break

    if not candidates:
        return None
    candidates.sort(key=lambda item: item.start_utc)
    return candidates[0]


def resolve_live_session(now: Optional[datetime] = None,
                         year: Optional[int] = None,
                         session: Optional[requests.Session] = None
                         ) -> Optional[LiveSessionRef]:
    """Find the session to attach to, preferring F1's own index.

    Falls back to the FastF1 schedule for weekends that F1 has not indexed
    yet, which is how an upcoming session is picked up before it starts.
    """
    try:
        found = find_live_session(now=now, year=year, session=session)
    except RuntimeError as exc:
        print(f"[live] {exc}")
        found = None
    if found is not None:
        return found
    return find_scheduled_session(now=now, year=year)
