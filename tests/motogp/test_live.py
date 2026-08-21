"""Live polling of the MotoGP timing feed and turning a snapshot into a frame."""
import json
import os
import threading

import pytest

from src.motogp import live as mlive, geometry, models
from src.motogp.client import MotoGPClient

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")


def _live_fixture():
    with open(os.path.join(FIXTURES, "livetiming_lite.json")) as handle:
        return json.load(handle)


def _client():
    return MotoGPClient(getter=lambda url: _live_fixture())


def test_poller_fetches_and_notifies():
    updates = []
    poller = mlive.MotoGPLivePoller(_client(), on_update=updates.append)
    snapshot = poller.poll_once()
    assert isinstance(snapshot, models.LiveTiming)
    assert snapshot.num_laps == 7
    assert updates and updates[0] is snapshot


def test_poller_loop_runs_on_interval_and_stops():
    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            stop.set()

    stop = threading.Event()
    poller = mlive.MotoGPLivePoller(_client(), on_update=lambda s: None,
                                    interval_s=0.01, sleep=fake_sleep)
    poller.run(stop)
    # Looped a few times then honoured the stop event.
    assert ticks["n"] >= 3
    assert poller.poll_count >= 3


def test_snapshot_to_frame_places_riders_by_order_and_gap():
    circuit = geometry.circuit_from_path(
        "M0,0 L1000,0 L1000,1000 L0,1000 Z", length_m=4000.0)
    live = models.parse_livetiming(_live_fixture())
    frame = mlive.live_frame(live, circuit)

    drivers = frame["drivers"]
    leader_no = str(live.riders[0].number)
    # The leader is classified first and sits ahead of the rider one place back.
    assert drivers[leader_no]["position"] == 1
    second_no = str(live.riders[1].number)
    assert drivers[second_no]["position"] == 2
    # A trailing rider sits behind the leader on track distance.
    assert drivers[second_no]["dist"] <= drivers[leader_no]["dist"]
    # Every rider lands on the centreline.
    line = circuit.track_line
    for code, car in drivers.items():
        x, y = line.point_at(car["dist"] % circuit.length_m)
        assert car["x"] == pytest.approx(x, abs=1.0)
        assert car["y"] == pytest.approx(y, abs=1.0)


def test_live_colours_come_from_the_feed():
    circuit = geometry.circuit_from_path("M0,0 L10,0 L10,10 L0,10 Z", 400.0)
    live = models.parse_livetiming(_live_fixture())
    frame = mlive.live_frame(live, circuit)
    colours = frame["driver_colors"]
    leader = live.riders[0]
    assert colours[str(leader.number)] == mlive._hex_to_rgb(leader.color)


def test_live_engine_appends_frames_and_reports_metadata():
    circuit = geometry.circuit_from_path(
        "M0,0 L1000,0 L1000,1000 L0,1000 Z", length_m=4000.0)
    engine = mlive.MotoGPLiveEngine(_client(), circuit, poll_interval_s=0.5)
    engine._poller.poll_once()
    assert len(engine.frames) == 1
    assert engine.total_laps() == 7
    assert engine.driver_colors()
    assert "LIVE" in engine.status_text()
    latest = engine.frames.latest
    assert "drivers" in latest and latest["t"] == 0.0
    # A second poll stamps a later time so the window advances.
    engine._poller.poll_once()
    assert len(engine.frames) == 2
    assert engine.frames.latest["t"] > 0


def test_live_engine_start_seeds_then_stops():
    circuit = geometry.circuit_from_path("M0,0 L10,0 L10,10 L0,10 Z", 400.0)
    engine = mlive.MotoGPLiveEngine(_client(), circuit, poll_interval_s=0.01)
    engine.start()
    assert len(engine.frames) >= 1          # first frame seeded synchronously
    assert engine.state.drivers              # state carries the running order
    engine.stop()                            # signals the poller to stop
