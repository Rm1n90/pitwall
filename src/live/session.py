"""Entry point for watching a session live.

Brings up the track geometry, the live engine and the replay window in the
right order, and reports clearly when a session cannot be watched yet.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from src.live.config import LiveConfig, SOURCE_SIMULATED
from src.live.engine import LiveRaceEngine
from src.live.projection import TrackProjector
from src.live.schedule import (
    LiveSessionRef,
    describe_wait,
    find_next_scheduled_session,
    find_session_by_path,
    resolve_live_session,
)
from src.lib.track_geometry import TrackLine
from src.live.track_reference import get_track_reference

# How long to wait for the first frame before opening the window anyway. The
# window shows a "waiting for data" screen until cars appear.
FIRST_FRAME_TIMEOUT_S = 25.0


class LiveSessionUnavailable(RuntimeError):
    """Raised when there is no session to watch right now."""


def resolve_session(config: LiveConfig,
                    session_path: Optional[str] = None,
                    now: Optional[datetime] = None) -> LiveSessionRef:
    """Work out which session to attach to.

    Args:
        config: Live configuration.
        session_path: Explicit feed path, which overrides discovery.
        now: Override for the current time, used by tests.

    Raises:
        LiveSessionUnavailable: when nothing is live and no path was given.
    """
    if session_path:
        found = find_session_by_path(session_path)
        if found is not None:
            return found
        # An unindexed path is still usable: the feeds are served by path.
        return LiveSessionRef(
            year=int(str(session_path).split("/", 1)[0] or 0),
            key=0, path=session_path, session_type="", name="Live Session",
            meeting_name="Live Session", country="", location="",
            circuit_short_name="",
            start_utc=now or datetime.now(timezone.utc), end_utc=None,
        )

    found = resolve_live_session(now=now)
    if found is not None:
        return found

    upcoming = find_next_scheduled_session(now=now)
    if upcoming is not None:
        raise LiveSessionUnavailable(
            f"No session is running right now. Next up: {upcoming.title} "
            f"in {describe_wait(upcoming.seconds_until_start(now))} "
            f"({upcoming.start_utc:%Y-%m-%d %H:%M} UTC)."
        )
    raise LiveSessionUnavailable(
        "No session is running right now and no upcoming session was found."
    )


def build_projector(session_ref: LiveSessionRef,
                    refresh: bool = False) -> TrackProjector:
    """Load the circuit geometry needed to place cars on track.

    Raises:
        LiveSessionUnavailable: when no reference lap can be found for the
            circuit, which makes drawing the track impossible.
    """
    event = session_ref.meeting_name or session_ref.location
    reference = get_track_reference(
        session_ref.year, event,
        event_key=f"{event}_{session_ref.year}", refresh=refresh,
    )
    if reference is None:
        raise LiveSessionUnavailable(
            f"No track layout could be built for {event}. Watch or download "
            f"any earlier session at this circuit once, then try again."
        )
    projector = TrackProjector(
        reference.example_lap["X"], reference.example_lap["Y"],
        reference.length_m,
    )
    projector.reference = reference
    try:
        projector.track_line = TrackLine(
            reference.example_lap["X"].to_numpy(float),
            reference.example_lap["Y"].to_numpy(float),
        )
    except Exception as exc:
        print(f"[live] no track line available for position repair: {exc}")
        projector.track_line = None
    return projector


def start_engine(session_ref: LiveSessionRef, projector: TrackProjector,
                 config: LiveConfig) -> LiveRaceEngine:
    """Start the engine and wait briefly for its first frame."""
    engine = LiveRaceEngine(
        session_ref, projector, config,
        track_line=getattr(projector, "track_line", None),
    )
    engine.start()

    deadline = time.monotonic() + FIRST_FRAME_TIMEOUT_S
    while time.monotonic() < deadline:
        if len(engine.frames) > 0:
            return engine
        time.sleep(0.25)

    print("[live] no frames yet; opening the window anyway. "
          "Diagnostics: " + str(engine.diagnostics()))
    return engine


def run_live_session(config: Optional[LiveConfig] = None,
                     session_path: Optional[str] = None,
                     ready_file: Optional[str] = None,
                     visible_hud: bool = True,
                     refresh_track: bool = False) -> None:
    """Watch a live session in the replay window.

    Raises:
        LiveSessionUnavailable: when no session can be attached to.
    """
    config = config or LiveConfig()
    session_ref = resolve_session(config, session_path)

    print(f"[live] attaching to {session_ref.title}")
    print(f"[live] feed path: {session_ref.path}")
    if config.source == SOURCE_SIMULATED:
        print(f"[live] simulated replay at {config.simulated_speed}x")

    projector = build_projector(session_ref, refresh=refresh_track)
    reference = getattr(projector, "reference", None)
    engine = start_engine(session_ref, projector, config)

    session_info = {
        "event_name": session_ref.meeting_name,
        "circuit_name": session_ref.location or session_ref.circuit_short_name,
        "country": session_ref.country,
        "year": session_ref.year,
        "round": None,
        "date": session_ref.start_utc.strftime("%B %d, %Y"),
        "total_laps": engine.total_laps(),
        "circuit_length_m": reference.length_m if reference else None,
    }

    # Imported here so that resolving a session never requires a display.
    from src.run_session import run_arcade_replay

    try:
        run_arcade_replay(
            frames=engine.frames,
            track_statuses=engine.track_statuses(),
            example_lap=reference.example_lap,
            drivers=list(engine.state.drivers.keys()),
            playback_speed=1.0,
            driver_colors=engine.driver_colors(),
            title=f"{session_ref.title} - LIVE",
            total_laps=engine.total_laps(),
            circuit_rotation=reference.rotation if reference else 0.0,
            visible_hud=visible_hud,
            ready_file=ready_file,
            session_info=session_info,
            session=None,
            enable_telemetry=True,
            race_control_messages=list(engine.state.race_control_messages),
            live_engine=engine,
        )
    finally:
        engine.stop()
