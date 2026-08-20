"""Tests that live frames match the shape the replay window expects."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.live.decoding import LiveMessage
from src.live.frame_builder import LiveFrameBuilder, build_track_statuses
from src.live.projection import TrackProjector
from src.live.state import LiveSessionState

SESSION_START = datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)

# Every key the offline pipeline puts on a driver in a frame.
REPLAY_DRIVER_KEYS = {
    "x", "y", "dist", "lap", "rel_dist", "tyre", "tyre_life",
    "position", "speed", "gear", "drs", "throttle", "brake", "in_pit",
}


def _utc(second: float) -> str:
    stamp = SESSION_START + timedelta(seconds=second)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


@pytest.fixture
def projector():
    angles = np.linspace(0, 2 * np.pi, 400)
    return TrackProjector(1000 * np.cos(angles), 1000 * np.sin(angles),
                          length_m=4000.0)


@pytest.fixture
def state():
    state = LiveSessionState()
    state.set_session_start(SESSION_START)
    state.apply(LiveMessage("DriverList", {
        "1": {"Tla": "NOR", "TeamColour": "F47600"},
        "16": {"Tla": "LEC", "TeamColour": "E8002D"},
    }))
    state.apply(LiveMessage("LapCount", {"CurrentLap": 5, "TotalLaps": 70}))
    state.apply(LiveMessage("TimingData", {"Lines": {
        "1": {"Position": "1", "NumberOfLaps": 5, "InPit": False,
              "GapToLeader": "", "IntervalToPositionAhead": {"Value": ""}},
        "16": {"Position": "2", "NumberOfLaps": 5, "InPit": False,
               "GapToLeader": "+1.234",
               "IntervalToPositionAhead": {"Value": "+1.234"}},
    }}))
    state.apply(LiveMessage("TimingAppData", {"Lines": {
        "1": {"Stints": [{"Compound": "MEDIUM", "TotalLaps": 11}]},
        "16": {"Stints": [{"Compound": "SOFT", "TotalLaps": 3}]},
    }}))
    for second, angle_1, angle_16 in ((0.0, 0.0, 0.1), (2.0, 0.05, 0.15)):
        state.apply(LiveMessage("Position", {"Position": [{
            "Timestamp": _utc(second),
            "Entries": {
                "1": {"Status": "OnTrack",
                      "X": 1000 * np.cos(angle_1 * 2 * np.pi),
                      "Y": 1000 * np.sin(angle_1 * 2 * np.pi), "Z": 0},
                "16": {"Status": "OnTrack",
                       "X": 1000 * np.cos(angle_16 * 2 * np.pi),
                       "Y": 1000 * np.sin(angle_16 * 2 * np.pi), "Z": 0},
            },
        }]}, "00:10:00.000"))
    state.apply(LiveMessage("CarData", {"Entries": [{
        "Utc": _utc(1.0),
        "Cars": {"1": {"Channels": {"0": 11000, "2": 300, "3": 7,
                                    "4": 100, "5": 0}}},
    }]}, "00:10:00.000"))
    return state


class TestFrameShape:
    def test_frame_matches_the_replay_contract(self, state, projector):
        frame = LiveFrameBuilder(state, projector).build(1.0)

        assert set(frame) >= {"t", "lap", "drivers"}
        assert frame["t"] == 1.0
        assert set(frame["drivers"]) == {"NOR", "LEC"}
        for entry in frame["drivers"].values():
            assert REPLAY_DRIVER_KEYS <= set(entry)

    def test_returns_none_before_any_position_arrives(self, projector):
        empty = LiveSessionState()
        assert LiveFrameBuilder(empty, projector).build(1.0) is None

    def test_uses_the_official_running_order(self, state, projector):
        frame = LiveFrameBuilder(state, projector).build(1.0)

        assert frame["drivers"]["NOR"]["position"] == 1
        assert frame["drivers"]["LEC"]["position"] == 2

    def test_assigns_a_position_to_drivers_without_timing_yet(self, state,
                                                              projector):
        state.timing["16"].pop("Position")
        frame = LiveFrameBuilder(state, projector).build(1.0)

        positions = sorted(d["position"] for d in frame["drivers"].values())
        assert positions == [1, 2]

    def test_carries_telemetry_from_the_car_feed(self, state, projector):
        entry = LiveFrameBuilder(state, projector).build(1.0)["drivers"]["NOR"]

        assert entry["speed"] == 300
        assert entry["gear"] == 7
        assert entry["throttle"] == 100
        assert entry["brake"] == 0.0

    def test_defaults_telemetry_for_drivers_without_car_data(self, state,
                                                             projector):
        entry = LiveFrameBuilder(state, projector).build(1.0)["drivers"]["LEC"]
        assert entry["speed"] == 0.0
        assert entry["gear"] == 0

    def test_tyre_life_comes_from_the_running_stint(self, state, projector):
        drivers = LiveFrameBuilder(state, projector).build(1.0)["drivers"]

        assert drivers["NOR"]["tyre"] == 1.0   # MEDIUM
        assert drivers["NOR"]["tyre_life"] == 11
        assert drivers["LEC"]["tyre"] == 0.0   # SOFT

    def test_unknown_compound_does_not_break_the_frame(self, state, projector):
        state.app_data["1"]["Stints"] = [{"TotalLaps": 2}]
        entry = LiveFrameBuilder(state, projector).build(1.0)["drivers"]["NOR"]
        assert entry["tyre"] == -1.0

    def test_race_distance_accounts_for_completed_laps(self, state, projector):
        entry = LiveFrameBuilder(state, projector).build(1.0)["drivers"]["NOR"]
        # Four completed laps of a 4000 m circuit, plus this lap's progress.
        assert entry["dist"] >= 4 * 4000.0

    def test_lap_numbers_never_go_backwards(self, state, projector):
        builder = LiveFrameBuilder(state, projector)
        builder.build(1.0)
        state.timing["1"]["NumberOfLaps"] = 2  # a stale update

        assert builder.build(1.5)["drivers"]["NOR"]["lap"] == 5

    def test_weather_is_attached_when_available(self, state, projector):
        state.apply(LiveMessage("WeatherData", {
            "AirTemp": "30.6", "TrackTemp": "52.9", "Humidity": "25.5",
            "WindSpeed": "3.2", "WindDirection": "139", "Rainfall": "0",
        }))
        weather = LiveFrameBuilder(state, projector).build(1.0)["weather"]

        assert weather["air_temp"] == 30.6
        assert weather["rain_state"] == "DRY"

    def test_rainfall_switches_the_rain_state(self, state, projector):
        state.apply(LiveMessage("WeatherData", {"Rainfall": "1"}))
        weather = LiveFrameBuilder(state, projector).build(1.0)["weather"]
        assert weather["rain_state"] == "RAINING"

    def test_retired_cars_that_have_left_the_track_are_dropped(self, state,
                                                               projector):
        state.timing["16"]["Retired"] = True
        samples = state.samples["16"]
        for index in range(len(samples.on_track)):
            samples.on_track[index] = False

        frame = LiveFrameBuilder(state, projector).build(1.0)
        assert "LEC" not in frame["drivers"]


class TestSafetyCar:
    def test_no_safety_car_under_green_flag(self, state, projector):
        assert LiveFrameBuilder(state, projector).build(1.0)["safety_car"] is None

    def test_deploys_ahead_of_the_leader(self, state, projector):
        state.track_status["Status"] = "4"
        builder = LiveFrameBuilder(state, projector)

        first = builder.build(1.0)["safety_car"]
        assert first["phase"] == "deploying"
        assert 0.0 <= first["alpha"] <= 1.0

        settled = builder.build(6.0)["safety_car"]
        assert settled["phase"] == "on_track"
        assert settled["alpha"] == 1.0

    def test_fades_out_after_the_safety_car_comes_in(self, state, projector):
        builder = LiveFrameBuilder(state, projector)
        state.track_status["Status"] = "4"
        builder.build(1.0)
        state.track_status["Status"] = "1"

        returning = builder.build(2.0)["safety_car"]
        assert returning["phase"] == "returning"
        assert builder.build(10.0)["safety_car"] is None


class TestTrackStatuses:
    def test_exposes_the_timeline_in_replay_shape(self, state):
        state.apply(LiveMessage("TrackStatus", {"Status": "4"}, "00:10:10.000"))
        state.apply(LiveMessage("TrackStatus", {"Status": "1"}, "00:10:40.000"))

        statuses = build_track_statuses(state)
        assert [s["status"] for s in statuses] == ["4", "1"]
        assert set(statuses[0]) == {"status", "start_time", "end_time"}
        assert statuses[0]["end_time"] == statuses[1]["start_time"]
