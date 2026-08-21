"""Live MotoGP timing: poll the public feed and turn a snapshot into a frame.

The MotoGP live feed (``timing-gateway/livetiming-lite``) is unauthenticated
and updates roughly once per rider per lap. It carries running order, lap
counts, last lap times and gaps, but no track position. So live mode here is
exact for the timing tower (order, gaps, last lap, pit status, colours) and
approximate for the map: a rider ``gap_first`` seconds behind the leader is
placed that far back along the centreline, at the speed the lap length and
their last lap time imply.

This is deliberately separate from the F1 SignalR pipeline, whose message
topics do not apply to MotoGP.
"""

import threading
import time
from typing import Callable, Dict, Optional

from src.motogp import models

# Colour used when the feed omits a rider colour.
_DEFAULT_COLOUR = (200, 200, 200)

# Fallback lap time (seconds) when a rider has not set one yet, used only to
# convert a time gap into a track distance for the map.
_FALLBACK_LAP_S = 100.0


def _hex_to_rgb(value: Optional[str]):
    if not value:
        return _DEFAULT_COLOUR
    text = value.lstrip("#")
    if len(text) != 6:
        return _DEFAULT_COLOUR
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return _DEFAULT_COLOUR


def _laptime_to_seconds(text: Optional[str]) -> Optional[float]:
    """Parse a MotoGP lap time such as ``2'10.217`` into seconds."""
    if not text:
        return None
    text = text.strip()
    try:
        if "'" in text:
            minutes, rest = text.split("'", 1)
            return int(minutes) * 60 + float(rest)
        return float(text)
    except (ValueError, TypeError):
        return None


class MotoGPLivePoller:
    """Polls the live timing feed on an interval and notifies a callback.

    Args:
        client: A :class:`~src.motogp.client.MotoGPClient`.
        on_update: Called with each fresh :class:`~src.motogp.models.LiveTiming`.
        interval_s: Seconds between polls.
        sleep: Sleep function, injectable for testing.
    """

    def __init__(self, client, on_update: Callable[[models.LiveTiming], None],
                 interval_s: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep):
        self._client = client
        self._on_update = on_update
        self.interval_s = interval_s
        self._sleep = sleep
        self.poll_count = 0
        self.last_error: Optional[str] = None
        self.latest: Optional[models.LiveTiming] = None

    def poll_once(self) -> Optional[models.LiveTiming]:
        """Fetch one snapshot, store it, and notify. Never raises."""
        try:
            snapshot = self._client.live_timing()
        except Exception as exc:  # a poll failure must not stop the loop
            self.last_error = str(exc)
            return None
        finally:
            self.poll_count += 1
        self.latest = snapshot
        try:
            self._on_update(snapshot)
        except Exception as exc:  # pragma: no cover - callback must not kill us
            self.last_error = f"callback: {exc}"
        return snapshot

    def run(self, stop_event: threading.Event) -> None:
        """Poll until ``stop_event`` is set, sleeping ``interval_s`` between."""
        while not stop_event.is_set():
            self.poll_once()
            self._sleep(self.interval_s)


def live_frame(live: models.LiveTiming, circuit) -> Dict:
    """Build a single replay frame from a live timing snapshot.

    The leader anchors the map at a fixed reference distance; every other rider
    is placed behind by ``gap_first`` seconds converted to metres via the lap
    length and their last lap time. Order, lap and gaps come straight from the
    feed.
    """
    length_m = circuit.length_m
    line = circuit.track_line

    riders = [r for r in live.riders if r.number is not None]
    leader_lap = max((r.num_lap or 0 for r in riders), default=0)
    # Anchor the leader partway along the lap so trailing riders have room
    # behind without wrapping past the start line in the common case.
    leader_distance = leader_lap * length_m

    drivers: Dict[str, Dict] = {}
    colours: Dict[str, tuple] = {}
    for rider in riders:
        code = str(rider.number)
        colours[code] = _hex_to_rgb(rider.color)
        lap_s = _laptime_to_seconds(rider.last_lap_time) or _FALLBACK_LAP_S
        speed_mps = length_m / lap_s
        gap = rider.gap_first or 0.0
        distance = max(leader_distance - gap * speed_mps, 0.0)
        x, y = line.point_at(distance % length_m)
        drivers[code] = {
            "x": x, "y": y, "dist": distance,
            "lap": rider.num_lap or 0,
            "rel_dist": round((distance % length_m) / length_m, 4),
            "progress": round(distance / length_m, 6),
            "tyre": 0.0, "tyre_life": 0.0,
            "position": rider.pos if rider.pos > 0 else len(riders),
            "speed": speed_mps * 3.6,
            "gear": 0, "drs": 0, "throttle": 0.0, "brake": 0.0,
            "in_pit": rider.on_pit, "pit_stops": 0,
            "retired": rider.pos <= 0,
            "gap_first": gap,
        }

    return {
        "t": 0.0,
        "lap": leader_lap,
        "drivers": drivers,
        "driver_colors": colours,
        "total_laps": live.num_laps,
        "session_type": "R",
    }


class _LiveState:
    """The subset of live-session state the replay window reads.

    MotoGP's feed carries none of F1's race-control, pit-stop or championship
    detail, so these are empty; the window reads them all defensively.
    """

    def __init__(self):
        self.drivers = {}
        self.race_control_messages = []
        self.position_history = None
        self.championship_prediction = None

    def pit_stops_by_code(self):
        return {}


class MotoGPLiveEngine:
    """Drives a live MotoGP session into the replay window.

    A background poller fetches the timing feed on an interval and appends a
    frame to a shared buffer; the window's live controller follows the tail.
    This matches the engine surface the controller expects (``frames``,
    ``status_text``, ``stop`` and a few metadata methods) without any of F1's
    engine machinery.

    Args:
        client: A :class:`~src.motogp.client.MotoGPClient`.
        circuit: :class:`~src.motogp.geometry.CircuitGeometry` for the track.
        poll_interval_s: Seconds between timing-feed polls.
    """

    def __init__(self, client, circuit, poll_interval_s: float = 5.0):
        from src.live.buffer import LiveFrameBuffer

        self.circuit = circuit
        self.frames = LiveFrameBuffer(max_frames=5000)
        self.state = _LiveState()
        self._poller = MotoGPLivePoller(client, self._on_update,
                                        interval_s=poll_interval_s)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._colors: Dict[str, tuple] = {}
        self._total_laps: Optional[int] = None
        self._leader_lap = 0

    def _on_update(self, live: models.LiveTiming) -> None:
        frame = live_frame(live, self.circuit)
        # Stamp a monotonically increasing time so playback treats each poll as
        # the next moment on the session clock.
        frame["t"] = round(len(self.frames) * self._poller.interval_s, 3)
        self._colors = frame.get("driver_colors", {})
        self._total_laps = frame.get("total_laps")
        self._leader_lap = frame.get("lap", 0)
        self.state.drivers = frame["drivers"]
        self.frames.append(frame)

    def start(self) -> None:
        """Seed the first frame, then poll in the background."""
        self._poller.poll_once()
        self._thread = threading.Thread(
            target=self._poller.run, args=(self._stop,),
            daemon=True, name="motogp-live")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- metadata the live controller reads ------------------------------

    def status_text(self) -> str:
        if self._total_laps:
            return f"MotoGP LIVE — lap {self._leader_lap}/{self._total_laps}"
        return "MotoGP LIVE"

    def driver_colors(self) -> Dict[str, tuple]:
        return self._colors

    def total_laps(self) -> Optional[int]:
        return self._total_laps

    def track_statuses(self):
        return []
