"""Tests for projecting car coordinates onto the track."""

import numpy as np
import pytest

from src.live.projection import TrackProjector


@pytest.fixture
def circle():
    """A 1000-unit-radius circular 'circuit' with a known 6283 m lap."""
    angles = np.linspace(0, 2 * np.pi, 400)
    return TrackProjector(1000 * np.cos(angles), 1000 * np.sin(angles),
                          length_m=6283.0)


class TestTrackProjector:
    def test_rejects_a_reference_that_is_too_short(self):
        with pytest.raises(ValueError):
            TrackProjector([1.0], [1.0])

    def test_projects_points_to_a_lap_fraction(self, circle):
        assert circle.relative_distance(1000, 0) == pytest.approx(0.0, abs=1e-3)
        assert circle.relative_distance(0, 1000) == pytest.approx(0.25, abs=1e-3)
        assert circle.relative_distance(-1000, 0) == pytest.approx(0.5, abs=1e-3)

    def test_projects_points_that_are_off_the_line(self, circle):
        assert circle.relative_distance(0, 900) == pytest.approx(0.25, abs=1e-3)

    def test_batch_projection_matches_single_projection(self, circle):
        batch = circle.relative_distances([(1000, 0), (0, 1000)])
        assert batch[0] == pytest.approx(circle.relative_distance(1000, 0))
        assert batch[1] == pytest.approx(circle.relative_distance(0, 1000))

    def test_batch_projection_handles_no_points(self, circle):
        assert len(circle.relative_distances([])) == 0

    def test_point_at_is_the_inverse_of_projection(self, circle):
        x, y = circle.point_at(0.25)
        assert (x, y) == (pytest.approx(0, abs=20), pytest.approx(1000, abs=20))

    def test_point_at_wraps_around_the_lap(self, circle):
        assert circle.point_at(1.25) == pytest.approx(circle.point_at(0.25))

    def test_advance_moves_along_the_lap_in_metres(self, circle):
        quarter_lap_m = 6283.0 / 4
        assert circle.advance(0.0, quarter_lap_m) == pytest.approx(0.25, abs=1e-3)

    def test_advance_wraps_past_the_finish_line(self, circle):
        assert circle.advance(0.9, 6283.0 * 0.2) == pytest.approx(0.1, abs=1e-3)

    def test_falls_back_to_polyline_length_without_a_real_lap_length(self):
        angles = np.linspace(0, 2 * np.pi, 200)
        projector = TrackProjector(np.cos(angles), np.sin(angles))
        assert projector.length_m == pytest.approx(projector.polyline_length)
