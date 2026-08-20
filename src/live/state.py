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

from src.lib.lap_history import (
    SECTOR_NORMAL, SECTOR_OVERALL_BEST, SECTOR_PERSONAL_BEST,
)
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

# Gaps longer than this are reconstructed along the track rather than being
# crossed in a straight line. A healthy feed updates about four times a
# second, so this leaves it untouched.
REPAIR_GAP_S = 0.6

# A car must be moving for a gap to be worth reconstructing; one genuinely
# stopped in the pits or a gravel trap has to stay where it is.
REPAIR_MIN_KMH = 30.0

# A repeated coordinate carries no new information. Storing it would make the
# samples either side of a stall look 0.24 s apart when the car has really not
# been located for seconds, which hides the gap from the repair above.
MIN_POSITION_MOVE = 5.0

# When the feed has not located a car for longer than the render delay there
# is no later sample to interpolate towards, and the car would simply stop.
# For up to this long it is carried forward along the circuit at the speed the
# telemetry says it is doing. Beyond it the prediction is not worth trusting.
MAX_DEAD_RECKONING_S = 5.0


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

        # A feed that has lost a car repeats its last coordinate. Recording
        # those would disguise a multi-second stall as a healthy stream of
        # samples, so only genuine movement is stored.
        if self.times:
            moved = ((x - self.xs[-1]) ** 2 + (y - self.ys[-1]) ** 2) ** 0.5
            if moved < MIN_POSITION_MOVE:
                self.on_track[-1] = on_track
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

    def position_at(self, t: float, track_line=None
                    ) -> Optional[Tuple[float, float, bool]]:
        """Interpolate the car's position at time ``t``.

        Normally this is a straight line between the two samples either side
        of ``t``. When the position feed stalls those samples can be seconds
        apart, and a straight line then cuts across the circuit while the car
        appears to crawl. Given a ``track_line`` the car is walked along the
        circuit instead. See :mod:`src.lib.track_geometry`.

        Returns ``None`` when there is no sample at or before ``t``.
        """
        times = self.times
        if not times:
            return None
        if t <= times[0]:
            return self.xs[0], self.ys[0], self.on_track[0]
        if t >= times[-1]:
            if track_line is not None:
                ahead = self._dead_reckon(track_line, t)
                if ahead is not None:
                    return ahead[0], ahead[1], self.on_track[-1]
            return self.xs[-1], self.ys[-1], self.on_track[-1]

        index = bisect.bisect_right(times, t)
        t0, t1 = times[index - 1], times[index]
        span = t1 - t0
        if span <= 0:
            return self.xs[index], self.ys[index], self.on_track[index]
        ratio = (t - t0) / span

        if track_line is not None and span > REPAIR_GAP_S:
            followed = self._follow_track(track_line, index, ratio, span, t)
            if followed is not None:
                return followed[0], followed[1], self.on_track[index - 1]

        x = self.xs[index - 1] + (self.xs[index] - self.xs[index - 1]) * ratio
        y = self.ys[index - 1] + (self.ys[index] - self.ys[index - 1]) * ratio
        return x, y, self.on_track[index - 1]

    def _distance_travelled(self, start_t: float, end_t: float) -> float:
        """Integrate the speed channel between two times, in feed units.

        Returns 0.0 when there is no usable telemetry, which stops the caller
        from moving a car it knows nothing about.
        """
        if end_t <= start_t or not self.car_times:
            return 0.0

        times = [start_t]
        speeds = [float((self.car_at(start_t) or {}).get("speed", 0.0))]
        first = bisect.bisect_right(self.car_times, start_t)
        for index in range(first, len(self.car_times)):
            sample_t = self.car_times[index]
            if sample_t >= end_t:
                break
            times.append(sample_t)
            speeds.append(float(self.car_values[index].get("speed", 0.0)))
        times.append(end_t)
        speeds.append(float((self.car_at(end_t) or {}).get("speed", 0.0)))

        total = 0.0
        for i in range(len(times) - 1):
            step = times[i + 1] - times[i]
            average = 0.5 * (speeds[i] + speeds[i + 1])
            total += average / 3.6 * 10.0 * step
        return total

    def _dead_reckon(self, line, t: float):
        """Carry a car forward along the circuit past its last known position.

        Returns ``None`` when the car should simply stay where it is.
        """
        elapsed = t - self.times[-1]
        if elapsed <= 0 or elapsed > MAX_DEAD_RECKONING_S:
            return None
        # The speed channel is separate from the position feed and usually
        # still healthy, so a car that has actually stopped stops here too.
        if float((self.car_at(t) or {}).get("speed", 0.0)) < REPAIR_MIN_KMH:
            return None

        distance = self._distance_travelled(self.times[-1], t)
        if distance <= 0:
            return None

        arc, offset_x, offset_y = line.project(self.xs[-1], self.ys[-1])
        point_x, point_y = line.point_at(arc + distance)
        return point_x + offset_x, point_y + offset_y

    def _follow_track(self, line, index: int, ratio: float, span: float,
                      t: float):
        """Return a position along the circuit between two distant samples.

        Returns ``None`` when the reconstruction cannot be trusted, in which
        case the caller falls back to straight-line interpolation.
        """
        from src.lib.track_geometry import DISTANCE_TOLERANCE

        speed = float((self.car_at(t) or {}).get("speed", 0.0))
        if speed < REPAIR_MIN_KMH:
            return None

        start_arc, start_dx, start_dy = line.project(
            self.xs[index - 1], self.ys[index - 1])
        end_arc, end_dx, end_dy = line.project(self.xs[index], self.ys[index])
        along = line.forward_distance(start_arc, end_arc)

        # Cross-check against how far the car's own speed says it went,
        # adding whole laps when it covered more than one.
        implied = speed / 3.6 * 10.0 * span
        if implied > 0 and line.length > 0:
            laps = round((implied - along) / line.length)
            along += max(0, laps) * line.length
            if abs(implied - along) > DISTANCE_TOLERANCE * max(implied, 1.0):
                return None

        point_x, point_y = line.point_at(start_arc + ratio * along)
        return (point_x + start_dx + (end_dx - start_dx) * ratio,
                point_y + start_dy + (end_dy - start_dy) * ratio)

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

        #: Circuit centreline, used to reconstruct a stalled position feed.
        self.track_line = None
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
        #: ``{car_number: [PitStop, ...]}`` of published pit stop times.
        self.pit_stops: Dict[str, list] = {}
        #: Time left in the session, as published by race control.
        self.extrapolated_clock: dict = {}
        #: ``{code: [(lap, position), ...]}`` for the position chart.
        self.position_history: Dict[str, list] = {}
        #: Where the championship would stand if the session ended now.
        self.championship_prediction: dict = {}
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

    def _apply_pit_stops(self, message: LiveMessage) -> None:
        from src.lib.pit_stops import parse_pit_stop_series

        parsed = parse_pit_stop_series(message.data)
        for number, stops in parsed.items():
            # The feed resends the whole series, so replacing is correct and
            # avoids accumulating duplicates.
            self.pit_stops[str(number)] = stops

    def _apply_championship_prediction(self, message: LiveMessage) -> None:
        from src.lib.standings import parse_prediction

        parsed = parse_prediction(message.data)
        if parsed["drivers"] or parsed["teams"]:
            # Each driver's code makes the projection usable without the
            # window having to map car numbers itself.
            for number, row in parsed["drivers"].items():
                row["code"] = self.driver_code(number)
            self.championship_prediction = parsed

    def _apply_lap_series(self, message: LiveMessage) -> None:
        from src.lib.position_history import from_lap_series, merge

        update = from_lap_series(message.data, self.driver_code)
        if update:
            merge(self.position_history, update)

    def _apply_extrapolated_clock(self, message: LiveMessage) -> None:
        if isinstance(message.data, dict):
            merge_patch(self.extrapolated_clock, message.data)

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

    def best_lap_time(self, number: str) -> Optional[float]:
        """The driver's quickest lap of the session so far."""
        entry = (self.timing.get(str(number)) or {}).get("BestLapTime")
        if isinstance(entry, dict):
            return parse_lap_time(entry.get("Value"))
        return None

    def sector_status(self, number: str) -> List[int]:
        """How the driver's three most recent sectors compare.

        The feed states outright whether a sector was the fastest anyone has
        managed or merely the driver's own best, so nothing has to be inferred
        from the undocumented status codes.
        """
        sectors = (self.timing.get(str(number)) or {}).get("Sectors")
        if isinstance(sectors, dict):
            # Updates address individual sectors by index rather than
            # resending the whole array.
            sectors = [sectors[key] for key in sorted(sectors, key=str)]
        if not isinstance(sectors, list):
            return [SECTOR_NORMAL] * 3

        statuses = []
        for sector in sectors[:3]:
            if not isinstance(sector, dict):
                statuses.append(SECTOR_NORMAL)
            elif sector.get("OverallFastest"):
                statuses.append(SECTOR_OVERALL_BEST)
            elif sector.get("PersonalFastest"):
                statuses.append(SECTOR_PERSONAL_BEST)
            else:
                statuses.append(SECTOR_NORMAL)
        return statuses + [SECTOR_NORMAL] * (3 - len(statuses))

    def laps_completed(self, number: str) -> Optional[int]:
        """How many laps the driver has completed, as the feed reports it."""
        value = (self.timing.get(str(number)) or {}).get("NumberOfLaps")
        try:
            return int(value)
        except (TypeError, ValueError):
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

    def time_remaining_s(self, t: Optional[float] = None) -> Optional[float]:
        """Return the seconds left in the session, if race control says.

        The feed is named for what it expects of a client: when
        ``Extrapolating`` is set, ``Remaining`` is only correct as at ``Utc``
        and the countdown has to be continued from there. F1 publishes an
        update when the clock starts or stops, not every second, so taking
        the value at face value leaves it frozen at the time of the last
        update. When the clock is held, under a red flag for instance,
        ``Extrapolating`` is false and the value stands as published.

        Args:
            t: Current replay time in seconds. Without it the published value
                is returned unadjusted.
        """
        from src.live.decoding import parse_stream_time

        remaining = parse_stream_time(
            self.extrapolated_clock.get("Remaining"))
        if remaining is None:
            return None
        seconds = remaining.total_seconds()

        if t is not None and self.extrapolated_clock.get("Extrapolating"):
            issued = parse_utc(self.extrapolated_clock.get("Utc"))
            if issued is not None and self.t0 is not None:
                elapsed = (self.t0 + timedelta(seconds=t) - issued
                           ).total_seconds()
                seconds -= elapsed

        return max(0.0, seconds)

    def pit_stops_by_code(self) -> Dict[str, list]:
        """Return published pit stop times keyed by driver code."""
        with self._lock:
            return {self.driver_code(number): stops
                    for number, stops in self.pit_stops.items()}

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
    "PitStopSeries": LiveSessionState._apply_pit_stops,
    "ExtrapolatedClock": LiveSessionState._apply_extrapolated_clock,
    "LapSeries": LiveSessionState._apply_lap_series,
    "ChampionshipPrediction": LiveSessionState._apply_championship_prediction,
    "Position": LiveSessionState._apply_position,
    "CarData": LiveSessionState._apply_car_data,
}
