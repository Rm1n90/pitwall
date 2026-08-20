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


class TestRoundedRectGeometry:
    """Panels share one rounded-rectangle shape, so it has to be right."""

    def _parts(self, radius=12.0):
        from src.render.shapes import rounded_rect_geometry
        return rounded_rect_geometry(0.0, 0.0, 200.0, 100.0, radius)

    def test_the_two_rectangles_cover_the_middle(self):
        horizontal, vertical, _corners = self._parts()
        assert horizontal[2] == 200.0          # full width
        assert horizontal[3] == 100.0 - 24.0   # inset top and bottom
        assert vertical[2] == 200.0 - 24.0
        assert vertical[3] == 100.0

    def test_there_is_a_quarter_at_each_corner(self):
        _h, _v, corners = self._parts()
        assert len(corners) == 4
        for _cx, _cy, _r, start, end in corners:
            assert end - start == pytest.approx(90.0)

    def test_the_corners_sit_a_radius_in_from_each_edge(self):
        _h, _v, corners = self._parts(radius=12.0)
        positions = sorted((cx, cy) for cx, cy, _r, _s, _e in corners)
        assert positions[0] == (12.0, 12.0)
        assert positions[-1] == (188.0, 88.0)

    def test_the_radius_cannot_exceed_the_panel(self):
        # A radius larger than the box would invert the middle rectangles.
        _h, _v, corners = self._parts(radius=500.0)
        assert corners[0][2] == 50.0  # half the shorter side

    def test_a_radius_of_zero_is_a_plain_rectangle(self):
        horizontal, vertical, corners = self._parts(radius=0.0)
        assert horizontal[3] == 100.0
        assert vertical[2] == 200.0
        assert all(corner[2] == 0.0 for corner in corners)

    def test_a_box_with_no_size_does_not_go_negative(self):
        from src.render.shapes import rounded_rect_geometry
        horizontal, vertical, _corners = rounded_rect_geometry(
            50.0, 50.0, 10.0, 10.0, 8.0)
        assert horizontal[2] >= 0 and horizontal[3] >= 0
        assert vertical[2] >= 0 and vertical[3] >= 0
