"""The live session engine.

One engine owns:

* the data source(s) feeding a :class:`~src.live.state.LiveSessionState`,
* a render clock that trails the newest received sample by a small delay,
* a worker thread that appends a frame to a :class:`LiveFrameBuffer` 25 times
  a second, exactly like the offline replay timeline.

Keeping the render clock behind the data lets every frame be interpolated
between two received samples instead of extrapolated past the last one, which
is what makes live playback look smooth rather than jumpy.
"""

import threading
import time
from typing import Callable, List, Optional

from src.live.buffer import LiveFrameBuffer
from src.live.config import (
    LIVE_DT,
    SOURCE_AUTO,
    SOURCE_SIGNALR,
    SOURCE_SIMULATED,
    SOURCE_STATIC,
    LiveConfig,
)
from src.live.decoding import LiveMessage
from src.live.frame_builder import LiveFrameBuilder, build_track_statuses
from src.live.projection import TrackProjector
from src.live.schedule import LiveSessionRef
from src.live.sources.base import LiveDataSource, SourceStatus
from src.live.state import LiveSessionState

# How long to wait for the SignalR feed to deliver car positions before
# bringing the public static feed up alongside it.
CAR_DATA_GRACE_S = 20.0

# The render clock never runs more than this far past the newest sample; if
# data stalls, playback holds rather than drifting into an empty future.
MAX_EXTRAPOLATION_S = 3.0

# When frame production falls further behind the render clock than this, the
# gap is skipped instead of being filled frame by frame. This happens after a
# long stall or when a source delivers a backlog on connect.
MAX_CATCHUP_S = 5.0


class LiveRaceEngine:
    """Produces replay frames from a live session.

    Args:
        session_ref: The session to attach to.
        projector: Track geometry used to place cars along the lap.
        config: User configuration.
        on_first_frame: Optional callback fired once the first frame exists,
            used to open the replay window only when there is something to
            draw.
    """

    def __init__(
        self,
        session_ref: LiveSessionRef,
        projector: TrackProjector,
        config: Optional[LiveConfig] = None,
        on_first_frame: Optional[Callable[[], None]] = None,
    ):
        self.session_ref = session_ref
        self.config = config or LiveConfig()
        self.state = LiveSessionState()
        self.projector = projector
        self.frames = LiveFrameBuffer(max_frames=self.config.max_frames)
        self.builder = LiveFrameBuilder(self.state, projector)
        self.on_first_frame = on_first_frame

        self._sources: List[LiveDataSource] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._render_t: Optional[float] = None
        self._last_tick: Optional[float] = None
        self._first_frame_sent = False
        self._static_started = False
        self._started_at: Optional[float] = None
        #: Set when the render clock had to hold because data stopped arriving.
        self.is_stalled = False
        self._frame_errors = 0

        if session_ref is not None:
            self.state.set_session_start(session_ref.start_utc)

    # -- lifecycle -------------------------------------------------------

    def _make_signalr_source(self) -> LiveDataSource:
        from src.live.sources.signalr import SignalRSource

        return SignalRSource(
            topics=self.config.topics,
            no_auth=self.config.no_auth,
            record_path=self.config.record_path,
        )

    def _make_static_source(self, start_at_end: bool = True) -> LiveDataSource:
        from src.live.sources.static_stream import StaticStreamSource

        return StaticStreamSource(
            session_path=self.session_ref.path,
            poll_interval_s=self.config.poll_interval_s,
            start_at_end=start_at_end,
        )

    def _make_simulated_source(self) -> LiveDataSource:
        from src.live.sources.simulated import SimulatedLiveSource

        return SimulatedLiveSource(
            session_path=self.session_ref.path,
            speed=self.config.simulated_speed,
            start_offset_s=self.config.simulated_start_offset_s,
        )

    def _build_sources(self) -> List[LiveDataSource]:
        source = self.config.source
        if source == SOURCE_SIMULATED:
            return [self._make_simulated_source()]
        if source == SOURCE_STATIC:
            return [self._make_static_source()]
        if source == SOURCE_SIGNALR:
            return [self._make_signalr_source()]
        # auto: SignalR for the lowest latency, with the public static feed
        # added later only if car positions never turn up.
        return [self._make_signalr_source()]

    def start(self) -> None:
        """Start the sources and the frame producing thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self._sources = self._build_sources()
        for source in self._sources:
            source.start(self._on_message)
        self._thread = threading.Thread(
            target=self._run, name="live-engine", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the frame thread and every source."""
        self._stop_event.set()
        for source in self._sources:
            source.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    # -- ingestion -------------------------------------------------------

    def _on_message(self, message: LiveMessage) -> None:
        self.state.apply(message)

    def _maybe_add_static_fallback(self) -> None:
        """Bring up the public feed when SignalR does not deliver positions.

        Car positions and telemetry are the only topics that may require a
        Formula 1 account on the SignalR feed. The static archive serves them
        to everyone, so it is used to fill the gap rather than failing.
        """
        if self._static_started or self.config.source != SOURCE_AUTO:
            return
        if self._started_at is None:
            return
        if time.monotonic() - self._started_at < CAR_DATA_GRACE_S:
            return
        if self.state.has_position_data():
            self._static_started = True  # nothing to do, positions arrived
            return

        print("[live] no car positions on the SignalR feed; "
              "adding the public timing archive for positions and telemetry")
        self._static_started = True
        source = self._make_static_source()
        source.start(self._on_message)
        self._sources.append(source)

    # -- render clock ----------------------------------------------------

    def _target_render_time(self) -> Optional[float]:
        """Return the newest time we are allowed to render, or ``None``."""
        latest = self.state.latest_sample_t
        if latest is None:
            return None
        return latest - self.config.delay_s

    def _advance_clock(self) -> Optional[float]:
        """Advance the render clock by real elapsed time, bounded by the data.

        Returns the render time to build the next frame for, or ``None`` when
        there is nothing to render yet.
        """
        target = self._target_render_time()
        if target is None:
            return None

        now = time.monotonic()
        if self._render_t is None:
            self._render_t = target
            self._last_tick = now
            return self._render_t

        elapsed = now - (self._last_tick or now)
        self._last_tick = now
        candidate = self._render_t + elapsed

        ceiling = target + MAX_EXTRAPOLATION_S
        if candidate > ceiling:
            # Data has stalled: hold the clock instead of running away.
            self.is_stalled = True
            candidate = ceiling
        else:
            self.is_stalled = False

        # If we have fallen a long way behind (a stall that recovered, or a
        # slow start), skip forward rather than replaying stale data.
        if target - candidate > 5.0:
            candidate = target

        self._render_t = max(self._render_t, candidate)
        return self._render_t

    # -- frame production ------------------------------------------------

    def _emit_frame(self, t: float) -> None:
        frame = self.builder.build(t)
        if frame is None:
            return
        self.frames.append(frame)
        if not self._first_frame_sent:
            self._first_frame_sent = True
            if self.on_first_frame is not None:
                try:
                    self.on_first_frame()
                except Exception as exc:
                    print(f"[live] first-frame callback failed: {exc}")

    def _tick(self, frame_t: Optional[float]) -> Optional[float]:
        """Produce the frames due this tick and return the next frame time."""
        self._maybe_add_static_fallback()

        render_t = self._advance_clock()
        if render_t is None:
            return frame_t

        if frame_t is None or render_t - frame_t > MAX_CATCHUP_S:
            # Nothing useful in the gap: jump straight to the render clock
            # rather than manufacturing minutes of stale frames.
            frame_t = render_t

        while frame_t <= render_t:
            self._emit_frame(frame_t)
            frame_t += LIVE_DT
        return frame_t

    def _run(self) -> None:
        next_tick = time.monotonic()
        frame_t: Optional[float] = None

        while not self._stop_event.is_set():
            try:
                frame_t = self._tick(frame_t)
            except Exception as exc:
                # A single bad frame must never take the live session down.
                self._frame_errors += 1
                if self._frame_errors in (1, 10, 100):
                    print(f"[live] frame generation error: {exc}")

            next_tick += LIVE_DT
            delay = next_tick - time.monotonic()
            if delay > 0:
                self._stop_event.wait(delay)
            else:
                # Fell behind; resynchronise the wall clock.
                next_tick = time.monotonic()

    # -- status ----------------------------------------------------------

    def track_statuses(self) -> List[dict]:
        """Track status timeline in the shape the replay window expects."""
        return build_track_statuses(self.state)

    def driver_colors(self) -> dict:
        return self.state.driver_colors()

    def total_laps(self) -> Optional[int]:
        return self.state.total_laps()

    @property
    def source_names(self) -> str:
        return "+".join(source.name for source in self._sources) or "none"

    def status_text(self) -> str:
        """One line summary for the on-screen live badge."""
        if not self._sources:
            return "LIVE: starting"
        statuses = {source.name: source.status for source in self._sources}
        if any(value == SourceStatus.CONNECTED for value in statuses.values()):
            if self.is_stalled:
                return f"LIVE: waiting for data ({self.source_names})"
            return f"LIVE: {self.source_names}"
        if any(value == SourceStatus.RECONNECTING for value in statuses.values()):
            return "LIVE: reconnecting"
        if all(value == SourceStatus.FAILED for value in statuses.values()):
            return "LIVE: disconnected"
        return f"LIVE: {self.source_names}"

    def diagnostics(self) -> dict:
        """Counters that make it obvious what the feed is (not) delivering."""
        return {
            "sources": {s.name: s.status for s in self._sources},
            "frames": len(self.frames),
            "render_t": self._render_t,
            "latest_sample_t": self.state.latest_sample_t,
            "position_messages": self.state.position_message_count,
            "car_messages": self.state.car_message_count,
            "drivers": len(self.state.samples),
            "rejected_samples": self.state.rejected_sample_count(),
            "stalled": self.is_stalled,
            "frame_errors": self._frame_errors,
        }
