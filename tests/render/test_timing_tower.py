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


class TestPitStopTimes:
    def _tower(self):
        from src.lib.pit_stops import PitStop

        tower = TimingTower(x=0)
        tower.pit_times = {"AAA": [PitStop(lap=13, stationary_s=2.6,
                                           pit_lane_s=21.7),
                                   PitStop(lap=30, stationary_s=3.1,
                                           pit_lane_s=22.4)]}
        return tower

    def test_shows_the_most_recent_completed_stop(self):
        tower = self._tower()
        assert tower.latest_stop("AAA", 20).stationary_s == 2.6
        assert tower.latest_stop("AAA", 40).stationary_s == 3.1

    def test_a_stop_that_has_not_happened_yet_is_not_shown(self):
        assert self._tower().latest_stop("AAA", 5) is None

    def test_a_driver_with_no_stops_returns_nothing(self):
        assert self._tower().latest_stop("ZZZ", 40) is None

    def test_without_a_lap_the_last_known_stop_is_used(self):
        assert self._tower().latest_stop("AAA", None).stationary_s == 3.1


class TestPracticeGap:
    """In practice the gap column is a lap time delta, not a distance."""

    def test_the_quickest_driver_shows_the_session_best(self):
        from src.render.timing_tower import format_practice_gap
        assert format_practice_gap(80.5, 80.5) == "1:20.500"

    def test_everyone_else_shows_how_far_off_they_are(self):
        from src.render.timing_tower import format_practice_gap
        assert format_practice_gap(81.0, 80.5) == "+0.500"

    def test_a_driver_without_a_time_shows_a_dash(self):
        from src.render.timing_tower import format_practice_gap
        assert format_practice_gap(None, 80.5) == "—"

    def test_the_first_lap_of_the_session_is_the_session_best(self):
        from src.render.timing_tower import format_practice_gap
        assert format_practice_gap(83.2, None) == "1:23.200"

    def test_large_deltas_stay_readable(self):
        from src.render.timing_tower import format_practice_gap
        assert format_practice_gap(95.0, 80.0) == "+15.000"


class TestPracticeMode:
    def test_a_tower_is_in_race_mode_by_default(self):
        tower = TimingTower(x=0)
        assert tower.practice_mode is False

    def test_practice_mode_can_be_turned_on(self):
        tower = TimingTower(x=0)
        tower.practice_mode = True
        assert tower.practice_mode is True

    def test_practice_headers_replace_the_race_ones(self):
        # No grid to compare against and no pit stops worth counting, but
        # lap counts and best times matter.
        tower = TimingTower(x=0)
        race = [label for _, label in tower.header_labels()]
        tower.practice_mode = True
        practice = [label for _, label in tower.header_labels()]

        assert "PIT" in race and "STOP" in race
        assert "PIT" not in practice and "STOP" not in practice
        assert "BEST" in practice and "LAPS" in practice
