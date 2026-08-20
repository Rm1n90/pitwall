"""Tests for the pill geometry behind the playback control tray."""

import pytest

pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.render.shapes import pill_geometry  # noqa: E402


class TestPillGeometry:
    def test_the_ends_are_half_the_height_across(self):
        _body, left, right = pill_geometry(100.0, 50.0, 200.0, 40.0)
        assert left[2] == 20.0
        assert right[2] == 20.0

    def test_the_pill_spans_the_full_width(self):
        _body, left, right = pill_geometry(100.0, 50.0, 200.0, 40.0)
        assert left[0] - left[2] == pytest.approx(0.0)
        assert right[0] + right[2] == pytest.approx(200.0)

    def test_the_body_bridges_the_two_ends(self):
        body, left, right = pill_geometry(100.0, 50.0, 200.0, 40.0)
        assert body[2] == pytest.approx(right[0] - left[0])
        assert body[3] == 40.0

    def test_the_ends_sit_on_the_centre_line(self):
        _body, left, right = pill_geometry(100.0, 50.0, 200.0, 40.0)
        assert left[1] == 50.0
        assert right[1] == 50.0

    def test_a_pill_as_wide_as_it_is_tall_is_a_circle(self):
        body, left, right = pill_geometry(100.0, 50.0, 40.0, 40.0)
        assert body[2] == 0.0
        assert left[0] == right[0] == 100.0

    def test_a_pill_narrower_than_its_height_does_not_invert(self):
        # Negative body width would draw a rectangle backwards.
        body, _left, _right = pill_geometry(100.0, 50.0, 10.0, 40.0)
        assert body[2] == 0.0
