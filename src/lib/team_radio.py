"""Team radio clips.

F1 publishes the radio messages it broadcasts, as short MP3s with a timestamp
and the car they belong to. They are in the timing archive rather than the
SignalR subscription, so a replay fetches them for the session and a live
session polls for them.
"""

import json
from dataclasses import dataclass
from typing import List
from urllib.request import urlopen

STATIC_BASE_URL = "https://livetiming.formula1.com/static/"
FEED_NAME = "TeamRadio"
REQUEST_TIMEOUT = 20


@dataclass(frozen=True)
class RadioClip:
    """One team radio message.

    Attributes:
        time_s: Replay time the message was broadcast at.
        code: Driver code, where known, otherwise the car number.
        url: Full address of the clip.
    """

    time_s: float
    code: str
    url: str


def parse_captures(payload, session_path: str, time_offset,
                   code_for_number=None) -> List[RadioClip]:
    """Return the clips in a feed payload.

    Args:
        payload: The feed's payload.
        session_path: Feed path, used to build each clip's full address.
        time_offset: Callable turning a UTC timestamp into replay seconds, or
            ``None`` to leave every clip at time zero.
        code_for_number: Callable turning a car number into a driver code.
    """
    if not isinstance(payload, dict):
        return []
    captures = payload.get("Captures")
    if isinstance(captures, dict):
        captures = [captures[key] for key in sorted(captures, key=str)]
    if not isinstance(captures, list):
        return []

    base = session_path if session_path.endswith("/") else session_path + "/"
    clips = []
    for capture in captures:
        if not isinstance(capture, dict):
            continue
        path = capture.get("Path")
        if not path:
            continue

        number = str(capture.get("RacingNumber") or "")
        code = code_for_number(number) if code_for_number else number

        moment = 0.0
        if time_offset is not None:
            try:
                moment = float(time_offset(capture.get("Utc")))
            except Exception:
                moment = 0.0

        clips.append(RadioClip(
            time_s=moment,
            code=str(code or number or "?"),
            url=f"{STATIC_BASE_URL}{base}{path}",
        ))
    clips.sort(key=lambda clip: clip.time_s)
    return clips


def fetch_captures(session_path: str, time_offset=None,
                   code_for_number=None) -> List[RadioClip]:
    """Download the team radio clips for a session feed path."""
    base = session_path if session_path.endswith("/") else session_path + "/"
    url = f"{STATIC_BASE_URL}{base}{FEED_NAME}.json"
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
    except Exception as e:
        print(f"Team radio unavailable: {e}")
        return []
    return parse_captures(payload, base, time_offset, code_for_number)


def to_payload(clips: List[RadioClip]) -> List[dict]:
    """Return a JSON-friendly form for the telemetry stream."""
    return [{"time": clip.time_s, "code": clip.code, "url": clip.url}
            for clip in clips]


def fetch_for_session(session, time_offset_s: float = 0.0) -> List[RadioClip]:
    """Fetch a session's radio clips, timed against the replay clock.

    Args:
        session: A loaded FastF1 session.
        time_offset_s: Session time that the replay counts as zero.

    Returns an empty list when the clips or the session's time origin are
    unavailable, since radio is a nice-to-have rather than something to fail
    a replay over.
    """
    from src.lib.pit_stops import session_feed_path

    path = session_feed_path(session)
    if not path:
        return []

    # The timing feed's own origin, which session times are measured from.
    # It is only available once telemetry has been loaded.
    try:
        origin = session.t0_date
    except Exception as e:
        print(f"Team radio needs the session's time origin: {e}")
        origin = None

    def _code(number):
        try:
            return session.get_driver(str(number))["Abbreviation"]
        except Exception:
            return number

    if origin is None:
        return fetch_captures(path, None, _code)

    from src.live.decoding import parse_utc

    def _offset(utc):
        parsed = parse_utc(utc)
        if parsed is None:
            return 0.0
        # `origin` is naive UTC, so compare like with like.
        return (parsed.replace(tzinfo=None) - origin).total_seconds() \
            - time_offset_s

    return fetch_captures(path, _offset, _code)
