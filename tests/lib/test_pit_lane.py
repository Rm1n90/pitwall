"""Tests for tracing the pit lane from telemetry."""

import numpy as np
import pandas as pd
import pytest

from src.lib import pit_lane


def _trace(length_units, points=60, x0=0.0):
    xs = np.linspace(x0, x0 + length_units, points)
    return np.column_stack((xs, np.full(points, 500.0)))


class TestPathLength:
    def test_measures_a_straight_run(self):
        assert pit_lane._path_length([(0, 0), (30, 40)]) == pytest.approx(50.0)

    def test_a_single_point_has_no_length(self):
        assert pit_lane._path_length([(1, 1)]) == 0.0


class TestSmooth:
    def test_averages_out_wobble(self):
        noisy = [(float(i), 0.0 if i % 2 else 10.0) for i in range(40)]
        smoothed = pit_lane._smooth(noisy, window=9)
        ys = [y for _, y in smoothed]
        assert max(ys) - min(ys) < 6.0

    def test_a_short_path_is_returned_as_is(self):
        points = [(0.0, 0.0), (1.0, 1.0)]
        assert pit_lane._smooth(points, window=9) == points


class _FakeLaps:
    def __init__(self, frame, telemetry):
        self._frame = frame
        self._telemetry = telemetry

    def pick_drivers(self, number):
        return _FakeLaps(self._frame, self._telemetry)

    def sort_values(self, column):
        return _FakeLaps(self._frame.sort_values(column), self._telemetry)

    def iterrows(self):
        return self._frame.iterrows()

    @property
    def iloc(self):
        outer = self

        class _Slicer:
            def __getitem__(self, item):
                return _FakeTelemetry(outer._telemetry)
        return _Slicer()


class _FakeTelemetry:
    def __init__(self, frame):
        self._frame = frame

    def get_telemetry(self):
        return self._frame


class _FakeSession:
    def __init__(self, frame, telemetry, drivers=("1", "2", "3", "4")):
        self.drivers = list(drivers)
        self.laps = _FakeLaps(frame, telemetry)


def _session(lane_units=3710.0, visit_s=22.0):
    laps = pd.DataFrame({
        "LapNumber": [12, 13],
        "PitInTime": [pd.Timedelta(seconds=100), pd.NaT],
        "PitOutTime": [pd.NaT, pd.Timedelta(seconds=100 + visit_s)],
    })
    n = 60
    telemetry = pd.DataFrame({
        "SessionTime": pd.to_timedelta(
            np.linspace(100, 100 + visit_s, n), unit="s"),
        "X": np.linspace(0, lane_units, n),
        "Y": np.full(n, 500.0),
    })
    return _FakeSession(laps, telemetry)


class TestExtractFromSession:
    def test_traces_a_pit_lane_of_a_believable_length(self):
        points = pit_lane.extract_from_session(_session())
        assert points is not None
        assert pit_lane.MIN_LANE_M <= \
            pit_lane._path_length(points) / 10 <= pit_lane.MAX_LANE_M

    def test_rejects_a_session_whose_cars_never_move(self):
        # This is what a degraded position feed looks like: the car appears
        # stationary through its whole stop.
        assert pit_lane.extract_from_session(_session(lane_units=0.0)) is None

    def test_rejects_a_trace_that_is_far_too_long(self):
        assert pit_lane.extract_from_session(_session(lane_units=90_000.0)) is None

    def test_rejects_an_implausibly_long_visit(self):
        assert pit_lane.extract_from_session(_session(visit_s=600.0)) is None

    def test_a_session_with_no_stops_yields_nothing(self):
        laps = pd.DataFrame({
            "LapNumber": [1, 2], "PitInTime": [pd.NaT, pd.NaT],
            "PitOutTime": [pd.NaT, pd.NaT]})
        telemetry = pd.DataFrame({
            "SessionTime": pd.to_timedelta([0, 1], unit="s"),
            "X": [0.0, 1.0], "Y": [0.0, 1.0]})
        assert pit_lane.extract_from_session(
            _FakeSession(laps, telemetry)) is None


class TestCache:
    def test_round_trips(self, tmp_path):
        points = [(1.0, 2.0), (3.0, 4.0)]
        pit_lane.save_cached(str(tmp_path), "Test GP 2026", points)
        assert pit_lane.load_cached(str(tmp_path), "Test GP 2026") == points

    def test_a_missing_cache_returns_nothing(self, tmp_path):
        assert pit_lane.load_cached(str(tmp_path), "Nothing") is None

    def test_a_corrupt_cache_is_ignored(self, tmp_path):
        pit_lane.save_cached(str(tmp_path), "Broken", [(0.0, 0.0)])
        path = pit_lane._cache_path(str(tmp_path), "Broken")
        with open(path, "wb") as handle:
            handle.write(b"not a pickle")
        assert pit_lane.load_cached(str(tmp_path), "Broken") is None

    def test_cache_names_are_filesystem_safe(self, tmp_path):
        path = pit_lane._cache_path(str(tmp_path), "São Paulo / GP 2026")
        assert "/" not in path.rsplit("/", 1)[-1]
