"""Tests for speed trap readings."""

import pytest

from src.lib.speed_traps import SpeedTraps, from_lap_times


@pytest.fixture
def traps():
    return SpeedTraps({
        "AAA": [(100.0, {"st": 320.0}), (200.0, {"st": 330.0}),
                (300.0, {"st": 325.0})],
        "BBB": [(150.0, {"st": 340.0, "i1": 290.0})],
    })


class TestBestFor:
    def test_tracks_the_best_so_far(self, traps):
        assert traps.best_for("AAA", 150.0)["st"] == 320.0
        assert traps.best_for("AAA", 250.0)["st"] == 330.0

    def test_a_slower_later_reading_does_not_replace_it(self, traps):
        assert traps.best_for("AAA", 350.0)["st"] == 330.0

    def test_nothing_before_the_first_reading(self, traps):
        assert traps.best_for("AAA", 50.0) == {}

    def test_an_unknown_driver_has_nothing(self, traps):
        assert traps.best_for("ZZZ", 500.0) == {}


class TestSessionBest:
    def test_finds_the_fastest_anyone_has_gone(self, traps):
        assert traps.session_best(500.0)["st"] == 340.0

    def test_changes_as_the_session_runs(self, traps):
        assert traps.session_best(120.0)["st"] == 320.0

    def test_covers_every_measuring_point(self, traps):
        assert traps.session_best(500.0)["i1"] == 290.0


class TestSnapshot:
    def test_flags_the_driver_leading_a_trap(self, traps):
        assert traps.snapshot("BBB", 500.0)["st"].is_session_best is True

    def test_does_not_flag_a_slower_driver(self, traps):
        assert traps.snapshot("AAA", 500.0)["st"].is_session_best is False

    def test_is_empty_before_any_reading(self, traps):
        assert traps.snapshot("AAA", 10.0) == {}


class TestBadData:
    def test_ignores_missing_and_zero_speeds(self):
        traps = SpeedTraps({"AAA": [
            (100.0, {"st": None}), (200.0, {"st": 0.0}), (300.0, {"st": 300.0}),
        ]})
        assert traps.best_for("AAA", 400.0) == {"st": 300.0}

    def test_a_driver_with_no_readings_is_dropped(self):
        assert SpeedTraps({"AAA": []}).drivers == []

    def test_no_data_at_all(self):
        assert SpeedTraps({}).session_best(10.0) == {}
        assert SpeedTraps(None).drivers == []


class TestFromLapTimes:
    def test_reads_the_replay_clock_and_speeds(self):
        traps = from_lap_times({"AAA": [
            {"replay_end_time_s": 90.0, "speed_st": 320.0, "speed_i1": 280.0},
            {"replay_end_time_s": 180.0, "speed_st": 335.0},
        ]})
        assert traps.best_for("AAA", 200.0) == {"st": 335.0, "i1": 280.0}

    def test_skips_laps_without_a_replay_time(self):
        traps = from_lap_times({"AAA": [{"speed_st": 320.0}]})
        assert traps.drivers == []

    def test_skips_laps_with_no_speeds(self):
        traps = from_lap_times({"AAA": [{"replay_end_time_s": 90.0}]})
        assert traps.drivers == []
