"""Tests for looking up lap times at a point in the replay."""

import pytest

from src.lib.lap_history import LapHistory


def _lap(number, seconds, replay_end, session_end=None):
    entry = {
        "lap": number,
        "time_s": seconds,
        "replay_end_time_s": replay_end,
        "end_time_s": session_end if session_end is not None
        else replay_end + 3248.0,
    }
    return entry


@pytest.fixture
def history():
    return LapHistory({
        "AAA": [_lap(1, 92.0, 92.0), _lap(2, 90.0, 182.0),
                _lap(3, 91.0, 273.0)],
        "BBB": [_lap(1, 95.0, 95.0), _lap(2, 89.0, 184.0)],
    })


class TestTimeBase:
    def test_uses_the_replay_clock_not_the_session_clock(self):
        # Frames count from zero; lap entries also carry a session clock that
        # starts thousands of seconds later. Mixing them up made every driver
        # look like they had completed only a handful of laps.
        history = LapHistory({"AAA": [_lap(1, 92.0, 92.0, session_end=3340.0)]})
        assert history.last_lap("AAA", 100.0) == 92.0
        assert history.last_lap("AAA", 50.0) is None

    def test_falls_back_to_the_line_crossing_time(self):
        history = LapHistory({"AAA": [
            {"time_s": 90.0, "replay_line_time_s": 90.0},
        ]})
        assert history.last_lap("AAA", 100.0) == 90.0


class TestLastLap:
    def test_returns_the_most_recent_completed_lap(self, history):
        assert history.last_lap("AAA", 200.0) == 90.0
        assert history.last_lap("AAA", 300.0) == 91.0

    def test_nothing_before_the_first_lap_is_complete(self, history):
        assert history.last_lap("AAA", 10.0) is None

    def test_an_unknown_driver_returns_nothing(self, history):
        assert history.last_lap("ZZZ", 500.0) is None


class TestPersonalBest:
    def test_tracks_the_best_so_far(self, history):
        assert history.personal_best("AAA", 100.0) == 92.0
        assert history.personal_best("AAA", 200.0) == 90.0

    def test_a_slower_later_lap_does_not_replace_it(self, history):
        assert history.personal_best("AAA", 300.0) == 90.0


class TestSessionBest:
    def test_finds_the_quickest_driver_so_far(self, history):
        best, holder = history.session_best(300.0)
        assert (best, holder) == (89.0, "BBB")

    def test_changes_hands_as_the_session_runs(self, history):
        assert history.session_best(100.0) == (92.0, "AAA")

    def test_is_unknown_before_anyone_completes_a_lap(self, history):
        assert history.session_best(10.0) == (None, None)


class TestSnapshot:
    def test_returns_everything_the_tower_needs(self, history):
        snapshot = history.snapshot(300.0)
        assert snapshot["last_laps"] == {"AAA": 91.0, "BBB": 89.0}
        assert snapshot["personal_bests"] == {"AAA": 90.0, "BBB": 89.0}
        assert snapshot["session_best"] == 89.0
        assert snapshot["session_best_code"] == "BBB"

    def test_is_empty_before_the_first_lap(self, history):
        snapshot = history.snapshot(0.0)
        assert snapshot["last_laps"] == {}
        assert snapshot["session_best"] is None


class TestBadData:
    def test_ignores_laps_without_a_time(self):
        history = LapHistory({"AAA": [
            {"time_s": None, "replay_end_time_s": 90.0},
            _lap(2, 91.0, 181.0),
        ]})
        assert history.last_lap("AAA", 500.0) == 91.0

    def test_ignores_non_positive_lap_times(self):
        history = LapHistory({"AAA": [_lap(1, -1.0, 90.0)]})
        assert history.drivers == []

    def test_survives_no_data_at_all(self):
        assert LapHistory({}).snapshot(10.0)["last_laps"] == {}
        assert LapHistory(None).drivers == []
