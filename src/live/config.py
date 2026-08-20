"""Configuration for live session playback."""

import os
from dataclasses import dataclass, field
from typing import Optional

# Rendering timeline of the replay window. Live frames must be produced at the
# same rate so that playback maths in the replay window stays valid.
LIVE_FPS = 25
LIVE_DT = 1.0 / LIVE_FPS

# How far behind the newest received sample the render clock runs. A small
# delay lets us interpolate *between* two received position samples instead of
# extrapolating past the last one, which removes almost all visible jitter.
DEFAULT_SIGNALR_DELAY_S = 2.0
DEFAULT_STATIC_DELAY_S = 8.0

# Roughly two hours of frames at 25 FPS. Older frames are trimmed to keep
# memory bounded during very long sessions (red flags, delays).
DEFAULT_MAX_FRAMES = 180_000

SOURCE_AUTO = "auto"
SOURCE_SIGNALR = "signalr"
SOURCE_STATIC = "static"
SOURCE_SIMULATED = "simulated"

VALID_SOURCES = (SOURCE_AUTO, SOURCE_SIGNALR, SOURCE_STATIC, SOURCE_SIMULATED)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"Warning: ignoring invalid value for {name}: {raw!r}")
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class LiveConfig:
    """User-facing knobs for a live session.

    Attributes:
        source: Which data source to use. ``auto`` prefers the SignalR feed
            and transparently falls back to the public static stream for the
            car position/telemetry topics when they are not delivered.
        delay_s: Render delay behind the newest received sample, in seconds.
            Lower means less latency but more chance of visible stutter.
        poll_interval_s: How often the static-stream source re-requests the
            tail of each feed file.
        record_path: Optional path for saving the raw feed. The recording is
            compatible with :class:`fastf1.livetiming.data.LiveTimingData`, so
            a live session can be re-analysed afterwards.
        no_auth: Skip the F1 account token entirely (SignalR source only).
        max_frames: Upper bound on frames retained in memory.
        simulated_session: ``(year, round_number, session_type)`` used by the
            ``simulated`` source to replay a past session at wall-clock speed.
        simulated_start_offset_s: Where in the simulated session to start.
        simulated_speed: Wall-clock multiplier for the simulated source.
    """

    source: str = SOURCE_AUTO
    delay_s: Optional[float] = None
    poll_interval_s: float = 2.0
    record_path: Optional[str] = None
    no_auth: bool = False
    max_frames: int = DEFAULT_MAX_FRAMES
    simulated_session: Optional[tuple] = None
    simulated_start_offset_s: float = 0.0
    simulated_speed: float = 1.0
    topics: tuple = field(default_factory=lambda: (
        "Heartbeat", "DriverList", "SessionInfo", "SessionStatus",
        "SessionData", "TrackStatus", "LapCount", "TimingData",
        "TimingAppData", "TimingStats", "WeatherData",
        "RaceControlMessages", "ExtrapolatedClock", "LapSeries",
        "ChampionshipPrediction",
        "Position.z", "CarData.z",
    ))

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(
                f"Unknown live source {self.source!r}; "
                f"expected one of {', '.join(VALID_SOURCES)}"
            )
        if self.delay_s is None:
            self.delay_s = _env_float(
                "F1_LIVE_DELAY",
                DEFAULT_STATIC_DELAY_S if self.source == SOURCE_STATIC
                else DEFAULT_SIGNALR_DELAY_S,
            )
        self.delay_s = max(0.0, float(self.delay_s))
        self.poll_interval_s = max(0.5, float(self.poll_interval_s))
        self.max_frames = max(LIVE_FPS * 60, int(self.max_frames))
        if not self.no_auth:
            self.no_auth = _env_bool("F1_LIVE_NO_AUTH", False)
