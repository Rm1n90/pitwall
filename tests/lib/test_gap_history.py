"""Tests for the gap-to-leader history behind the gap chart."""

import pytest

from src.lib.gap_history import (
    from_lap_times, merge, parse_gap, to_payload, update_from_frame,
)


def _lap(number, end):
    return {"lap": number, "replay_end_time_s": end, "time_s": 90.0}


class TestParseGap:
    """Live frames carry the gap as the feed writes it, which is a string."""

    def test_reads_a_gap_in_seconds(self):
        assert parse_gap("+1.234") == pytest.approx(1.234)

    def test_reads_a_gap_without_a_sign(self):
        assert parse_gap("1.234") == pytest.approx(1.234)

    def test_the_leader_has_no_gap(self):
        assert parse_gap("") is None

    def test_a_lapped_car_has_no_gap_in_seconds(self):
        # The feed switches to laps once a car is a lap down, and a lap is
        # not a number of seconds.
        assert parse_gap("1L") is None
        assert parse_gap("+2L") is None

    def test_the_opening_lap_placeholder_is_not_a_gap(self):
        assert parse_gap("LAP 1") is None

    def test_nonsense_is_not_a_gap(self):
        assert parse_gap(None) is None
        assert parse_gap("banana") is None


class TestFromLapTimes:
    """Offline the gap follows from when each car crossed the line."""

    def test_the_leader_is_on_zero(self):
        history = from_lap_times({
            "AAA": [_lap(1, 90.0)],
            "BBB": [_lap(1, 92.5)],
        })
        assert history["AAA"] == [(1, 0.0)]

    def test_a_gap_is_the_difference_at_the_line(self):
        history = from_lap_times({
            "AAA": [_lap(1, 90.0)],
            "BBB": [_lap(1, 92.5)],
        })
        assert history["BBB"] == [(1, pytest.approx(2.5))]

    def test_the_gap_follows_whoever_leads_that_lap(self):
        # The lead changes on lap two, so the reference changes with it.
        history = from_lap_times({
            "AAA": [_lap(1, 90.0), _lap(2, 183.0)],
            "BBB": [_lap(1, 92.5), _lap(2, 181.0)],
        })
        assert history["BBB"][1] == (2, pytest.approx(0.0))
        assert history["AAA"][1] == (2, pytest.approx(2.0))

    def test_a_driver_who_retires_simply_stops(self):
        history = from_lap_times({
            "AAA": [_lap(1, 90.0), _lap(2, 180.0)],
            "BBB": [_lap(1, 92.5)],
        })
        assert [lap for lap, _ in history["BBB"]] == [1]

    def test_laps_without_a_crossing_time_are_skipped(self):
        history = from_lap_times({
            "AAA": [{"lap": 1, "time_s": 90.0}],
        })
        assert history == {}

    def test_no_laps_means_no_history(self):
        assert from_lap_times({}) == {}
        assert from_lap_times(None) == {}


class TestUpdateFromFrame:
    """Live there is no lap table, so the gap is read off each frame."""

    def _frame(self, drivers, lap=5):
        return {"lap": lap, "drivers": drivers}

    def test_records_a_gap_when_a_driver_completes_a_lap(self):
        history = {}
        update_from_frame(history, self._frame({
            "AAA": {"lap": 5, "gap_to_leader": ""},
            "BBB": {"lap": 5, "gap_to_leader": "+1.234"},
        }))
        assert history["BBB"] == [(5, pytest.approx(1.234))]
        assert history["AAA"] == [(5, 0.0)]

    def test_one_entry_per_driver_per_lap(self):
        history = {}
        frame = self._frame({"BBB": {"lap": 5, "gap_to_leader": "+1.2"}})
        update_from_frame(history, frame)
        update_from_frame(history, frame)
        assert len(history["BBB"]) == 1

    def test_a_new_lap_adds_an_entry(self):
        history = {}
        update_from_frame(history, self._frame(
            {"BBB": {"lap": 5, "gap_to_leader": "+1.2"}}))
        update_from_frame(history, self._frame(
            {"BBB": {"lap": 6, "gap_to_leader": "+1.8"}}))
        assert [lap for lap, _ in history["BBB"]] == [5, 6]

    def test_a_lapped_car_is_not_recorded(self):
        history = {}
        update_from_frame(history, self._frame(
            {"BBB": {"lap": 5, "gap_to_leader": "1L"}}))
        assert "BBB" not in history

    def test_a_frame_without_drivers_changes_nothing(self):
        history = {}
        update_from_frame(history, {"lap": 5, "drivers": {}})
        assert history == {}


class TestMergeAndPayload:
    def test_merge_keeps_the_longer_history(self):
        base = {"AAA": [(1, 0.0)]}
        merge(base, {"AAA": [(1, 0.0), (2, 0.0)], "BBB": [(1, 1.0)]})
        assert len(base["AAA"]) == 2
        assert "BBB" in base

    def test_merge_does_not_shorten_what_it_already_has(self):
        base = {"AAA": [(1, 0.0), (2, 0.0)]}
        merge(base, {"AAA": [(1, 0.0)]})
        assert len(base["AAA"]) == 2

    def test_payload_is_json_friendly(self):
        import json
        payload = to_payload({"AAA": [(1, 0.0), (2, 1.5)]})
        json.dumps(payload)
        assert payload["AAA"] == [[1, 0.0], [2, 1.5]]
