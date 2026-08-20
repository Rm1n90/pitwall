"""Accumulated state of a live F1 session.

Every message that arrives from a source is folded into this object. It keeps
the newest value of each timing field plus a short history of car position and
telemetry samples, which the frame builder interpolates between.

All time handling is done in absolute UTC because that is the only clock every
feed agrees on: position samples carry ``Timestamp``, car telemetry carries
``Utc``, and the timing feeds carry a stream-relative timestamp that is mapped
onto UTC using the offset learned from the other two.
"""

import bisect
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.live.decoding import (
    LiveMessage,
    channels_to_telemetry,
    iter_car_samples,
    iter_position_samples,
    merge_patch,
    parse_gmt_offset,
    parse_lap_time,
    parse_stream_time,
    parse_utc,
)

# Position samples arrive at roughly 4 Hz. Half an hour of history is enough
# for interpolation and for rebuilding after a stall, without growing forever.
POSITION_HISTORY = 8_000
CAR_HISTORY = 8_000

# Track status codes as used by the replay window.
TRACK_STATUS_ALL_CLEAR = "1"

# Position coordinates are in 1/10 m, so 1111 units/s is 400 km/h. Roughly one
# position sample in a thousand places a car hundreds of metres away for a
# single update; anything implying more than this is treated as such a glitch.
MAX_PLAUSIBLE_SPEED_UNITS_PER_S = 1111.0

# Consecutive rejections that are accepted anyway. A car really can appear
# somewhere new (recovered to the pits, feed resynchronised after a red flag),
# and after this many agreeing samples the new location is believed.
MAX_CONSECUTIVE_REJECTIONS = 3

# Samples closer together than this are dropped: the feed's timestamps jitter,
# and dividing by a near-zero interval turns that jitter into a teleport.
MIN_SAMPLE_INTERVAL_S = 0.05

# Beyond this gap a large jump is expected rather than suspicious.
PLAUSIBILITY_MAX_GAP_S = 3.0


def _is_reachable(first, second) -> bool:
    """True when a car could plausibly travel between two samples."""
    gap = second[0] - first[0]
    if gap <= 0:
        return False
    if gap > PLAUSIBILITY_MAX_GAP_S:
        return True
    distance = ((second[1] - first[1]) ** 2 + (second[2] - first[2]) ** 2) ** 0.5
    return distance / gap <= MAX_PLAUSIBLE_SPEED_UNITS_PER_S


class DriverSamples:
    """Position and telemetry history for a single driver."""

    __slots__ = ("times", "xs", "ys", "on_track", "car_times", "car_values",
                 "rejected_count", "_pending", "_pending_agreement")

    def __init__(self):
        self.times: deque = deque(maxlen=POSITION_HISTORY)
        self.xs: deque = deque(maxlen=POSITION_HISTORY)
        self.ys: deque = deque(maxlen=POSITION_HISTORY)
        self.on_track: deque = deque(maxlen=POSITION_HISTORY)
        self.car_times: deque = deque(maxlen=CAR_HISTORY)
        self.car_values: deque = deque(maxlen=CAR_HISTORY)
        #: Total rejections, surfaced through the engine's diagnostics.
        self.rejected_count = 0
        self._pending = None
        self._pending_agreement = 0

    def _is_plausible(self, t: float, x: float, y: float) -> bool:
        """Reject single-sample glitches that teleport a car across the map."""
        if not self.times:
            return True
        gap = t - self.times[-1]
        if gap <= 0 or gap > PLAUSIBILITY_MAX_GAP_S:
            return True
        distance = ((x - self.xs[-1]) ** 2 + (y - self.ys[-1]) ** 2) ** 0.5
        return distance / gap <= MAX_PLAUSIBLE_SPEED_UNITS_PER_S

    def add_position(self, t: float, x: float, y: float, on_track: bool) -> None:
        # Out-of-order and near-duplicate samples happen constantly; keep the
        # series sorted and spaced so interpolation stays correct.
        if self.times and t - self.times[-1] < MIN_SAMPLE_INTERVAL_S:
            return

        if not self._is_plausible(t, x, y):
            self.rejected_count += 1
            # A distant reading is only believed once consecutive readings
            # agree with each other, which distinguishes a real relocation
            # (recovery to the pits, feed resync) from a burst of glitches.
            pending = self._pending
            if pending is not None and _is_reachable(pending, (t, x, y)):
                self._pending_agreement += 1
            else:
                self._pending_agreement = 1
            self._pending = (t, x, y, on_track)
            if self._pending_agreement < MAX_CONSECUTIVE_REJECTIONS:
                return

        self._pending = None
        self._pending_agreement = 0

        self.times.append(t)
        self.xs.append(x)
        self.ys.append(y)
        self.on_track.append(on_track)

    def add_car(self, t: float, values: dict) -> None:
        if self.car_times and t <= self.car_times[-1]:
            return
        # Pedal channels drop out regularly; carry the last known value
        # forward so the telemetry traces do not flicker to zero.
        if self.car_values:
            previous = self.car_values[-1]
            for key in ("throttle", "brake"):
                if values.get(key) is None:
                    values[key] = previous.get(key)
        for key in ("throttle", "brake"):
            if values.get(key) is None:
                values[key] = 0.0
        self.car_times.append(t)
        self.car_values.append(values)

    def position_at(self, t: float) -> Optional[Tuple[float, float, bool]]:
        """Linearly interpolate the car's position at time ``t``.

        Returns ``None`` when there is no sample at or before ``t``.
        """
        times = self.times
        if not times:
            return None
        if t <= times[0]:
            return self.xs[0], self.ys[0], self.on_track[0]
        if t >= times[-1]:
            return self.xs[-1], self.ys[-1], self.on_track[-1]

        index = bisect.bisect_right(times, t)
        t0, t1 = times[index - 1], times[index]
        span = t1 - t0
        if span <= 0:
            return self.xs[index], self.ys[index], self.on_track[index]
        ratio = (t - t0) / span
        x = self.xs[index - 1] + (self.xs[index] - self.xs[index - 1]) * ratio
        y = self.ys[index - 1] + (self.ys[index] - self.ys[index - 1]) * ratio
        return x, y, self.on_track[index - 1]

    def car_at(self, t: float) -> Optional[dict]:
        """Return the most recent telemetry sample at or before ``t``."""
        times = self.car_times
        if not times:
            return None
        if t <= times[0]:
            return self.car_values[0]
        if t >= times[-1]:
            return self.car_values[-1]
        index = bisect.bisect_right(times, t)
        return self.car_values[index - 1]

    @property
    def latest_time(self) -> Optional[float]:
        if self.times:
            return self.times[-1]
        return None


class LiveSessionState:
    """Thread-safe accumulator for one live session.

    The engine writes to it from the source thread and reads from the frame
    building thread, so every public method takes the internal lock.
    """

    def __init__(self):
        self._lock = threading.RLock()

        self.session_info: dict = {}
        self.session_status: str = ""
        self.drivers: Dict[str, dict] = {}
        self.timing: Dict[str, dict] = {}
        self.app_data: Dict[str, dict] = {}
        self.weather: dict = {}
        self.lap_count: dict = {}
        self.track_status: dict = {"Status": TRACK_STATUS_ALL_CLEAR,
                                   "Message": "AllClear"}
        self.track_status_history: List[dict] = []
        self.race_control_messages: List[dict] = []
        self.samples: Dict[str, DriverSamples] = {}

        #: UTC instant that frame time ``t = 0`` corresponds to.
        self.t0: Optional[datetime] = None
        #: Newest sample time seen, in frame seconds.
        self.latest_sample_t: Optional[float] = None
        #: Offset between the feeds' stream clock and UTC.
        self._stream_offset: Optional[timedelta] = None
        self._seen_rc_keys: set = set()
        self.position_message_count = 0
        self.car_message_count = 0

    @property
    def lock(self) -> threading.RLock:
        """Re-entrant lock guarding every field of this state."""
        return self._lock

    # -- time helpers ----------------------------------------------------

    def set_session_start(self, start_utc: datetime) -> None:
        """Pin frame time zero to a known session start."""
        with self._lock:
            if self.t0 is None:
                self.t0 = start_utc

    def _to_frame_time(self, utc: datetime) -> float:
        if self.t0 is None:
            self.t0 = utc
        return (utc - self.t0).total_seconds()

    def _note_sample_time(self, t: float) -> None:
        if self.latest_sample_t is None or t > self.latest_sample_t:
            self.latest_sample_t = t

    def _learn_stream_offset(self, stream_time: str, utc: datetime) -> None:
        """Learn how the feeds' stream clock maps onto UTC."""
        if self._stream_offset is not None or not stream_time:
            return
        offset = parse_stream_time(stream_time)
        if offset is not None:
            self._stream_offset = utc - offset

    def stream_time_to_frame_time(self, stream_time: str) -> Optional[float]:
        """Convert a feed timestamp string into frame seconds."""
        offset = parse_stream_time(stream_time)
        if offset is None or self._stream_offset is None:
            return None
        return self._to_frame_time(self._stream_offset + offset)

    # -- ingestion -------------------------------------------------------

    def apply(self, message: LiveMessage) -> None:
        """Fold one decoded message into the state."""
        handler = _HANDLERS.get(message.topic)
        if handler is None:
            return
        with self._lock:
            handler(self, message)

    def _apply_session_info(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        merge_patch(self.session_info, data)
        if self.t0 is None:
            start = parse_utc(self.session_info.get("StartDate"))
            if start is not None:
                offset = parse_gmt_offset(self.session_info.get("GmtOffset"))
                self.t0 = start - offset

    def _apply_session_status(self, message: LiveMessage) -> None:
        data = message.data
        if isinstance(data, dict):
            self.session_status = str(data.get("Status", self.session_status))

    def _apply_driver_list(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        for number, patch in data.items():
            if not isinstance(patch, dict):
                continue
            merge_patch(self.drivers.setdefault(str(number), {}), patch)

    def _apply_timing_data(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        for number, patch in (data.get("Lines") or {}).items():
            if isinstance(patch, dict):
                merge_patch(self.timing.setdefault(str(number), {}), patch)

    def _apply_timing_app_data(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        for number, patch in (data.get("Lines") or {}).items():
            if isinstance(patch, dict):
                merge_patch(self.app_data.setdefault(str(number), {}), patch)

    def _apply_weather(self, message: LiveMessage) -> None:
        if isinstance(message.data, dict):
            merge_patch(self.weather, message.data)

    def _apply_lap_count(self, message: LiveMessage) -> None:
        if isinstance(message.data, dict):
            merge_patch(self.lap_count, message.data)

    def _apply_track_status(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        merge_patch(self.track_status, data)
        status = str(self.track_status.get("Status", TRACK_STATUS_ALL_CLEAR))
        history = self.track_status_history
        if history and history[-1]["status"] == status:
            return
        # The stream timestamp cannot be mapped onto frame time until the
        # first position or telemetry sample has been seen, so the raw value
        # is kept and resolved on read instead.
        history.append({
            "status": status,
            "stream_time": message.stream_time,
            "t_hint": self.latest_sample_t,
            "message": str(self.track_status.get("Message", "")),
        })

    def _apply_race_control(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        entries = data.get("Messages")
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = (str(entry.get("Utc", "")), str(entry.get("Message", "")))
            if key in self._seen_rc_keys:
                continue
            self._seen_rc_keys.add(key)
            utc = parse_utc(entry.get("Utc"))
            self.race_control_messages.append({
                "time": round(self._to_frame_time(utc), 3) if utc else 0.0,
                "category": str(entry.get("Category", "")),
                "message": str(entry.get("Message", "")),
                "flag": str(entry.get("Flag", "")),
                "scope": str(entry.get("Scope", "")),
                "sector": str(entry.get("Sector", "")),
                "racing_number": str(entry.get("RacingNumber", "")),
            })

    def _apply_position(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        self.position_message_count += 1
        for utc, entries in iter_position_samples(data):
            self._learn_stream_offset(message.stream_time, utc)
            t = self._to_frame_time(utc)
            self._note_sample_time(t)
            for number, entry in entries.items():
                try:
                    x = float(entry["X"])
                    y = float(entry["Y"])
                except (KeyError, TypeError, ValueError):
                    continue
                status = str(entry.get("Status", "OnTrack"))
                on_track = status.lower() != "offtrack"
                samples = self.samples.setdefault(str(number), DriverSamples())
                samples.add_position(t, x, y, on_track)

    def _apply_car_data(self, message: LiveMessage) -> None:
        data = message.data
        if not isinstance(data, dict):
            return
        self.car_message_count += 1
        for utc, cars in iter_car_samples(data):
            self._learn_stream_offset(message.stream_time, utc)
            t = self._to_frame_time(utc)
            self._note_sample_time(t)
            for number, car in cars.items():
                channels = car.get("Channels") if isinstance(car, dict) else None
                if not isinstance(channels, dict):
                    continue
                samples = self.samples.setdefault(str(number), DriverSamples())
                samples.add_car(t, channels_to_telemetry(channels))

    # -- read helpers ----------------------------------------------------

    def snapshot_meta(self) -> dict:
        """Return a copy of the slow-moving session metadata."""
        with self._lock:
            return {
                "session_info": dict(self.session_info),
                "session_status": self.session_status,
                "track_status": dict(self.track_status),
                "lap_count": dict(self.lap_count),
                "weather": dict(self.weather),
                "drivers": {k: dict(v) for k, v in self.drivers.items()},
            }

    def driver_code(self, number: str) -> str:
        """Return a driver's three letter code, falling back to the number."""
        info = self.drivers.get(str(number)) or {}
        return str(info.get("Tla") or f"#{number}")

    def driver_colors(self) -> Dict[str, tuple]:
        """Return ``{code: (r, g, b)}`` for every known driver."""
        colors = {}
        with self._lock:
            for number, info in self.drivers.items():
                raw = str(info.get("TeamColour") or "").strip().lstrip("#")
                if len(raw) != 6:
                    continue
                try:
                    colors[self.driver_code(number)] = (
                        int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
                    )
                except ValueError:
                    continue
        return colors

    def total_laps(self) -> Optional[int]:
        value = self.lap_count.get("TotalLaps")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def current_lap(self) -> int:
        value = self.lap_count.get("CurrentLap")
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def current_stint(self, number: str) -> dict:
        """Return the driver's most recent stint entry."""
        stints = (self.app_data.get(str(number)) or {}).get("Stints")
        if isinstance(stints, dict):
            stints = [stints[key] for key in sorted(stints, key=str)]
        if not isinstance(stints, list) or not stints:
            return {}
        for stint in reversed(stints):
            if isinstance(stint, dict) and stint:
                return stint
        return {}

    def last_lap_time(self, number: str) -> Optional[float]:
        entry = (self.timing.get(str(number)) or {}).get("LastLapTime")
        if isinstance(entry, dict):
            return parse_lap_time(entry.get("Value"))
        return None

    def resolved_track_status_history(self) -> List[dict]:
        """Return the track status timeline with resolved frame times.

        Each entry gets a ``start_time``; ``end_time`` comes from the next
        entry and is ``None`` for the status currently in force.
        """
        with self._lock:
            resolved = []
            for entry in self.track_status_history:
                start = self.stream_time_to_frame_time(entry.get("stream_time"))
                if start is None:
                    start = entry.get("t_hint")
                if start is None:
                    start = resolved[-1]["start_time"] if resolved else 0.0
                if resolved and start < resolved[-1]["start_time"]:
                    start = resolved[-1]["start_time"]
                resolved.append({
                    "status": entry["status"],
                    "start_time": float(start),
                    "end_time": None,
                    "message": entry.get("message", ""),
                })
            for current, following in zip(resolved, resolved[1:]):
                current["end_time"] = following["start_time"]
            return resolved

    def rejected_sample_count(self) -> int:
        """Total number of implausible position samples that were dropped."""
        with self._lock:
            return sum(s.rejected_count for s in self.samples.values())

    def has_position_data(self) -> bool:
        with self._lock:
            return any(samples.times for samples in self.samples.values())


_HANDLERS = {
    "SessionInfo": LiveSessionState._apply_session_info,
    "SessionStatus": LiveSessionState._apply_session_status,
    "DriverList": LiveSessionState._apply_driver_list,
    "TimingData": LiveSessionState._apply_timing_data,
    "TimingAppData": LiveSessionState._apply_timing_app_data,
    "WeatherData": LiveSessionState._apply_weather,
    "LapCount": LiveSessionState._apply_lap_count,
    "TrackStatus": LiveSessionState._apply_track_status,
    "RaceControlMessages": LiveSessionState._apply_race_control,
    "Position": LiveSessionState._apply_position,
    "CarData": LiveSessionState._apply_car_data,
}
