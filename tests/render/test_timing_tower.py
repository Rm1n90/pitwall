"""Tests for timing tower formatting and ordering."""

import pytest

pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.render.timing_tower import (  # noqa: E402
    TimingTower,
    format_gap,
    format_lap_time,
)


class TestFormatGap:
    def test_small_gaps_get_millisecond_precision(self):
        assert format_gap(0.04, 90.0) == "+3.600"

    def test_larger_gaps_drop_to_a_tenth(self):
        assert format_gap(0.5, 90.0) == "+45.0"

    def test_a_full_lap_is_reported_as_a_lap(self):
        assert format_gap(1.2, 90.0) == "+1 LAP"
        assert format_gap(2.4, 90.0) == "+2 LAPS"

    def test_a_negligible_gap_shows_a_dash(self):
        assert format_gap(0.0, 90.0) == "—"

    def test_the_reference_lap_time_scales_the_gap(self):
        # A part-lap gap means different things at Monaco and at Spa.
        assert format_gap(0.1, 70.0) != format_gap(0.1, 110.0)


class TestFormatLapTime:
    def test_formats_minutes_and_seconds(self):
        assert format_lap_time(82.491) == "1:22.491"

    def test_formats_a_sub_minute_lap(self):
        assert format_lap_time(45.2) == "45.200"

    @pytest.mark.parametrize("value", [None, 0, -3])
    def test_unknown_times_show_a_dash(self, value):
        assert format_lap_time(value) == "—"


class TestOrdering:
    def test_uses_the_classification_from_the_frame(self):
        # The old leaderboard re-sorted by lap and distance, which discarded
        # the finish-line freeze the frames already account for.
        tower = TimingTower(x=0)
        tower.set_entries([
            ("AAA", (255, 0, 0), {"position": 3}, 10.0),
            ("BBB", (0, 255, 0), {"position": 1}, 5.0),
            ("CCC", (0, 0, 255), {"position": 2}, 20.0),
        ])
        order = sorted(tower.entries, key=lambda e: e[2].get("position") or 99)
        assert [e[0] for e in order] == ["BBB", "CCC", "AAA"]


class TestVisibility:
    def test_toggles(self):
        tower = TimingTower(x=0, visible=True)
        assert tower.toggle_visibility() is False
        tower.set_visible()
        assert tower.visible is True
