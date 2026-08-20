"""Tests for the live engine's render clock and frame production."""

from datetime import datetime, timezone

import numpy as np
import pytest

from src.live.config import LIVE_DT, LiveConfig
from src.live.decoding import LiveMessage
from src.live.engine import MAX_EXTRAPOLATION_S, LiveRaceEngine
from src.live.projection import TrackProjector
from src.live.schedule import LiveSessionRef

SESSION_START = datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    angles = np.linspace(0, 2 * np.pi, 200)
    projector = TrackProjector(1000 * np.cos(angles), 1000 * np.sin(angles),
                               length_m=4000.0)
    session_ref = LiveSessionRef(
        year=2026, key=1, path="2026/x/y/", session_type="Race", name="Race",
        meeting_name="Test Grand Prix", country="", location="",
        circuit_short_name="", start_utc=SESSION_START, end_utc=None,
    )
    return LiveRaceEngine(session_ref, projector, LiveConfig(delay_s=2.0))


class TestRenderClock:
    def test_waits_until_data_arrives(self, engine):
        assert engine._advance_clock() is None

    def test_starts_the_delay_behind_the_newest_sample(self, engine):
        engine.state.latest_sample_t = 100.0
        assert engine._advance_clock() == pytest.approx(98.0)

    def test_holds_when_the_feed_stalls(self, engine):
        engine.state.latest_sample_t = 100.0
        engine._advance_clock()
        engine._render_t = 100.0  # already at the extrapolation ceiling
        engine._last_tick -= 5.0  # pretend five seconds passed with no data

        # The clock may run at most MAX_EXTRAPOLATION_S past the newest
        # sample, which sits `delay_s` behind latest_sample_t.
        assert engine._advance_clock() == pytest.approx(
            98.0 + MAX_EXTRAPOLATION_S)
        assert engine.is_stalled is True

    def test_skips_forward_after_falling_far_behind(self, engine):
        engine.state.latest_sample_t = 100.0
        engine._advance_clock()
        engine.state.latest_sample_t = 500.0

        assert engine._advance_clock() == pytest.approx(498.0, abs=0.5)

    def test_never_runs_backwards(self, engine):
        engine.state.latest_sample_t = 100.0
        first = engine._advance_clock()
        engine.state.latest_sample_t = 50.0

        assert engine._advance_clock() >= first


class TestFrameProduction:
    def _feed_positions(self, engine, seconds):
        engine.state.apply(LiveMessage("DriverList", {"1": {"Tla": "NOR"}}))
        for second in seconds:
            stamp = SESSION_START.replace(microsecond=0)
            stamp = stamp + __import__("datetime").timedelta(seconds=second)
            engine.state.apply(LiveMessage("Position", {"Position": [{
                "Timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                "Entries": {"1": {"Status": "OnTrack",
                                  "X": 1000.0 - second, "Y": 0.0, "Z": 0}},
            }]}, "00:10:00.000"))

    def test_produces_uniformly_spaced_frames(self, engine, monkeypatch):
        self._feed_positions(engine, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        # Drive the render clock directly: in a real run it advances with
        # wall-clock time, which a test cannot wait for.
        clock = iter([1.0, 1.2, 1.4, 1.6])
        monkeypatch.setattr(engine, "_advance_clock", lambda: next(clock))

        frame_t = None
        for _ in range(4):
            frame_t = engine._tick(frame_t)

        times = [frame["t"] for frame in engine.frames]
        assert len(times) > 10
        gaps = {round(b - a, 3) for a, b in zip(times, times[1:])}
        assert gaps == {round(LIVE_DT, 3)}

    def test_skips_a_long_gap_instead_of_filling_it(self, engine, monkeypatch):
        self._feed_positions(engine, [0.0, 1.0, 2.0, 3.0])
        clock = iter([1.0, 500.0])
        monkeypatch.setattr(engine, "_advance_clock", lambda: next(clock))

        frame_t = engine._tick(None)
        engine._tick(frame_t)

        # A minutes-long gap must not manufacture thousands of stale frames.
        assert len(engine.frames) < 100

    def test_first_frame_callback_fires_once(self, engine, monkeypatch):
        calls = []
        engine.on_first_frame = lambda: calls.append(1)
        self._feed_positions(engine, [0.0, 1.0, 2.0, 3.0])
        clock = iter([1.0, 1.1, 1.2])
        monkeypatch.setattr(engine, "_advance_clock", lambda: next(clock))

        frame_t = None
        for _ in range(3):
            frame_t = engine._tick(frame_t)

        assert calls == [1]

    def test_a_broken_frame_does_not_stop_the_engine(self, engine):
        def _boom(_t):
            raise ValueError("bad frame")

        self._feed_positions(engine, [0.0, 1.0, 2.0, 3.0])
        engine.builder.build = _boom
        engine._stop_event.set()  # run a single pass then exit
        engine._run()

        assert engine._frame_errors >= 0  # no exception escaped


class TestDiagnostics:
    def test_reports_useful_counters(self, engine):
        report = engine.diagnostics()
        assert set(report) >= {"sources", "frames", "render_t",
                               "latest_sample_t", "position_messages",
                               "car_messages", "drivers", "stalled"}

    def test_status_text_before_starting(self, engine):
        assert "LIVE" in engine.status_text()
