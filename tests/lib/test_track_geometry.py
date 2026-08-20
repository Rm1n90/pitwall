"""Tests for track geometry and repair of a stalled position feed."""

import numpy as np
import pytest

from src.lib.track_geometry import (
    TrackLine,
    find_anchors,
    rebuild_positions,
)

RADIUS = 1000.0


@pytest.fixture
def circle():
    """A circular circuit, so expected geometry is known exactly."""
    angles = np.linspace(0, 2 * np.pi, 600)
    return TrackLine(RADIUS * np.cos(angles), RADIUS * np.sin(angles))


def _lap(line, n, speed_kmh=180.0):
    """Drive n samples round the line at a constant speed."""
    units_per_s = speed_kmh / 3.6 * 10.0
    dt = 0.24
    times = np.arange(n) * dt
    arcs = (np.arange(n) * units_per_s * dt) % line.length
    xy = np.array([line.point_at(a) for a in arcs])
    speeds = np.full(n, speed_kmh)
    return times, xy[:, 0].copy(), xy[:, 1].copy(), speeds


class TestTrackLine:
    def test_measures_the_lap_length(self, circle):
        assert circle.length == pytest.approx(2 * np.pi * RADIUS, rel=1e-3)

    def test_resamples_to_uniform_spacing(self, circle):
        # The raw telemetry clusters points in corners and leaves long gaps on
        # straights, which makes projection quantise badly.
        steps = np.hypot(np.diff(circle.xs), np.diff(circle.ys))
        assert steps.max() / steps.min() < 1.05

    def test_rejects_an_unusable_reference(self):
        with pytest.raises(ValueError):
            TrackLine([1.0], [1.0])

    def test_rejects_a_reference_of_identical_points(self):
        with pytest.raises(ValueError):
            TrackLine([5.0] * 10, [5.0] * 10)

    def test_projects_a_point_on_the_line(self, circle):
        arc, dx, dy = circle.project(RADIUS, 0.0)
        assert arc == pytest.approx(0.0, abs=circle.length * 0.01)
        assert (dx, dy) == (pytest.approx(0, abs=10), pytest.approx(0, abs=10))

    def test_projection_reports_the_sideways_offset(self, circle):
        # Two cars side by side must stay side by side.
        _, dx, dy = circle.project(RADIUS + 80.0, 0.0)
        assert np.hypot(dx, dy) == pytest.approx(80.0, abs=12)

    def test_point_at_wraps_past_the_finish_line(self, circle):
        assert circle.point_at(circle.length * 1.25) == \
            pytest.approx(circle.point_at(circle.length * 0.25))

    def test_forward_distance_wraps_the_short_way_round(self, circle):
        distance = circle.forward_distance(circle.length * 0.9,
                                           circle.length * 0.1)
        assert distance == pytest.approx(circle.length * 0.2, rel=1e-6)


class TestFindAnchors:
    def test_marks_every_sample_when_the_feed_is_healthy(self):
        x = np.arange(10, dtype=float) * 50
        y = np.zeros(10)
        assert find_anchors(x, y).sum() == 10

    def test_ignores_a_feed_repeating_itself(self):
        x = np.array([0.0, 0.0, 0.0, 100.0, 100.0, 200.0])
        y = np.zeros(6)
        assert list(find_anchors(x, y)) == [True, False, False, True, False, True]

    def test_handles_an_empty_series(self):
        assert find_anchors(np.array([]), np.array([])).size == 0


class TestRebuildPositions:
    def test_leaves_a_healthy_feed_untouched(self, circle):
        times, x, y, speeds = _lap(circle, 60)
        new_x, new_y, repaired = rebuild_positions(times, x, y, speeds, circle)

        assert repaired == 0
        assert np.array_equal(new_x, x)
        assert np.array_equal(new_y, y)

    def test_reconstructs_a_stalled_run(self, circle):
        times, x, y, speeds = _lap(circle, 60)
        truth_x, truth_y = x.copy(), y.copy()
        # The feed repeats sample 10 for two seconds, then catches up.
        for index in range(11, 20):
            x[index], y[index] = x[10], y[10]

        new_x, new_y, repaired = rebuild_positions(times, x, y, speeds, circle)

        assert repaired > 0
        # The car should be back near where it really was, not frozen.
        error = np.hypot(new_x[11:20] - truth_x[11:20],
                         new_y[11:20] - truth_y[11:20])
        assert error.max() < RADIUS * 0.1

    def test_reconstructed_cars_stay_on_the_track(self, circle):
        times, x, y, speeds = _lap(circle, 60)
        for index in range(11, 20):
            x[index], y[index] = x[10], y[10]

        new_x, new_y, _ = rebuild_positions(times, x, y, speeds, circle)

        # Straight-line interpolation would cut across the infield; following
        # the track keeps every car on the radius.
        radius = np.hypot(new_x[11:20], new_y[11:20])
        assert radius.min() > RADIUS * 0.9

    def test_a_stationary_car_is_left_where_it_is(self, circle):
        times, x, y, speeds = _lap(circle, 40)
        speeds[:] = 0.0
        for index in range(11, 25):
            x[index], y[index] = x[10], y[10]

        new_x, new_y, repaired = rebuild_positions(times, x, y, speeds, circle)

        assert repaired == 0
        assert new_x[20] == x[10]

    def test_does_nothing_without_a_track_line(self, circle):
        times, x, y, speeds = _lap(circle, 40)
        new_x, _, repaired = rebuild_positions(times, x, y, speeds, None)
        assert repaired == 0
        assert np.array_equal(new_x, x)

    def test_handles_a_very_short_series(self, circle):
        times = np.array([0.0, 0.1])
        _, _, repaired = rebuild_positions(
            times, np.array([0.0, 1.0]), np.array([0.0, 1.0]),
            np.array([100.0, 100.0]), circle)
        assert repaired == 0

    def test_never_modifies_the_caller_s_arrays(self, circle):
        times, x, y, speeds = _lap(circle, 60)
        for index in range(11, 20):
            x[index], y[index] = x[10], y[10]
        before = x.copy()

        rebuild_positions(times, x, y, speeds, circle)

        assert np.array_equal(x, before)
