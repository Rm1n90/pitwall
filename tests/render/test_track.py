"""Tests for building the circuit geometry.

Drawing needs a graphics context, so these cover the geometry and the data
handling; the drawing calls themselves are exercised by running the app.
"""

import numpy as np
import pytest

pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.render.track import (  # noqa: E402
    TrackRenderer,
    _curvature,
    _offset_edges,
    _resample,
    corner_labels_from_circuit_info,
)

RADIUS = 1000.0


@pytest.fixture
def circle_xy():
    angles = np.linspace(0, 2 * np.pi, 400)
    return RADIUS * np.cos(angles), RADIUS * np.sin(angles)


class TestResample:
    def test_returns_the_requested_number_of_points(self, circle_xy):
        xs, ys = _resample(*circle_xy, 250)
        assert len(xs) == 250 and len(ys) == 250

    def test_spaces_points_evenly_along_the_path(self):
        # Raw telemetry clusters points in corners; even spacing is what makes
        # kerbs and projection behave.
        xs = np.array([0.0, 1.0, 2.0, 100.0])
        ys = np.zeros(4)
        rx, _ = _resample(xs, ys, 5)
        steps = np.diff(rx)
        assert steps.max() == pytest.approx(steps.min(), rel=1e-6)

    def test_a_zero_length_path_is_returned_unchanged(self):
        xs = np.zeros(4)
        rx, ry = _resample(xs, xs, 10)
        assert len(rx) == 4


class TestOffsetEdges:
    def test_edges_sit_half_a_width_either_side(self, circle_xy):
        xs, ys = circle_xy
        (ox, oy), (ix, iy) = _offset_edges(xs, ys, 200.0)
        assert np.hypot(ox, oy).mean() == pytest.approx(RADIUS + 100, rel=0.01)
        assert np.hypot(ix, iy).mean() == pytest.approx(RADIUS - 100, rel=0.01)

    def test_the_edges_stay_the_track_width_apart(self, circle_xy):
        xs, ys = circle_xy
        (ox, oy), (ix, iy) = _offset_edges(xs, ys, 200.0)
        assert np.hypot(ox - ix, oy - iy).mean() == pytest.approx(200.0, rel=0.01)


class TestCurvature:
    def test_a_straight_does_not_bend(self):
        xs = np.linspace(0, 1000, 50)
        assert _curvature(xs, np.zeros(50)).max() < 1e-6

    def test_a_tighter_circle_bends_more(self):
        angles = np.linspace(0, 2 * np.pi, 200)
        wide = _curvature(1000 * np.cos(angles), 1000 * np.sin(angles))
        tight = _curvature(100 * np.cos(angles), 100 * np.sin(angles))
        assert np.median(tight) > np.median(wide)


class TestTrackRenderer:
    def test_builds_the_racing_surface_and_a_runoff_apron(self, circle_xy):
        renderer = TrackRenderer(*circle_xy, track_width=200.0)

        surface = np.hypot(renderer.outer_x - renderer.inner_x,
                           renderer.outer_y - renderer.inner_y)
        apron = np.hypot(renderer.runoff_out_x - renderer.runoff_in_x,
                         renderer.runoff_out_y - renderer.runoff_in_y)
        assert surface.mean() == pytest.approx(200.0, rel=0.02)
        assert apron.mean() > surface.mean()

    def test_flags_a_sensible_share_of_the_lap_as_corner(self, circle_xy):
        # A percentile keeps this stable whether the circuit is Monaco or
        # Monza; a fixed threshold produced kerbs too small to see.
        renderer = TrackRenderer(*circle_xy, track_width=200.0)
        share = renderer.is_corner.mean()
        assert 0.05 < share < 0.35

    def test_rejects_a_reference_that_is_too_short(self):
        with pytest.raises(Exception):
            TrackRenderer([0.0], [0.0], track_width=200.0)

    def test_accepts_a_session_without_corners_or_a_pit_lane(self, circle_xy):
        renderer = TrackRenderer(*circle_xy, track_width=200.0)
        assert renderer.corners == []
        assert renderer.pit_lane == []


class TestCornerLabels:
    def test_reads_numbers_and_letters(self):
        import pandas as pd

        class _Info:
            corners = pd.DataFrame({
                "X": [1.0, 2.0], "Y": [3.0, 4.0],
                "Number": [1, 1], "Letter": ["", "A"],
            })

        assert corner_labels_from_circuit_info(_Info()) == \
            [(1.0, 3.0, "1"), (2.0, 4.0, "1A")]

    def test_missing_information_is_not_an_error(self):
        class _Empty:
            corners = None

        assert corner_labels_from_circuit_info(_Empty()) == []
