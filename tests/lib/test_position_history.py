"""Tests for lap-by-lap running order."""

import pandas as pd
import pytest

from src.lib.position_history import (
    from_lap_series,
    from_session,
    merge,
    places_gained,
    positions_at,
    to_payload,
)


class _Session:
    def __init__(self, frame):
        self.laps = frame


def _laps(rows):
    return pd.DataFrame(rows, columns=["Driver", "LapNumber", "Position"])


class TestFromSession:
    def test_reads_a_position_for_every_lap(self):
        history = from_session(_Session(_laps([
            ["NOR", 1, 2.0], ["NOR", 2, 1.0], ["VER", 1, 1.0],
        ])))
        assert history["NOR"] == [(1, 2), (2, 1)]

    def test_sorts_by_lap(self):
        history = from_session(_Session(_laps([
            ["NOR", 3, 1.0], ["NOR", 1, 3.0], ["NOR", 2, 2.0],
        ])))
        assert [lap for lap, _ in history["NOR"]] == [1, 2, 3]

    def test_skips_laps_without_a_position(self):
        history = from_session(_Session(_laps([
            ["NOR", 1, None], ["NOR", 2, 1.0],
        ])))
        assert history["NOR"] == [(2, 1)]

    def test_rejects_positions_outside_the_field(self):
        history = from_session(_Session(_laps([
            ["NOR", 1, 0.0], ["NOR", 2, 99.0], ["NOR", 3, 5.0],
        ])))
        assert history["NOR"] == [(3, 5)]

    def test_a_session_without_laps_is_empty(self):
        assert from_session(_Session(pd.DataFrame())) == {}


class TestFromLapSeries:
    def _codes(self, number):
        return {"1": "NOR", "16": "LEC"}.get(number, number)

    def test_reads_a_list_of_positions(self):
        history = from_lap_series(
            {"1": {"RacingNumber": "1", "LapPosition": ["2", "1", "1"]}},
            self._codes)
        assert history["NOR"] == [(1, 2), (2, 1), (3, 1)]

    def test_reads_a_live_update_keyed_by_lap_index(self):
        history = from_lap_series(
            {"1": {"LapPosition": {"3": "4"}}}, self._codes)
        assert history["NOR"] == [(4, 4)]

    def test_ignores_entries_without_positions(self):
        assert from_lap_series({"1": {"RacingNumber": "1"}}, self._codes) == {}

    @pytest.mark.parametrize("payload", [None, "nope", []])
    def test_unusable_payloads_yield_nothing(self, payload):
        assert from_lap_series(payload, self._codes) == {}


class TestMerge:
    def test_adds_new_laps(self):
        base = {"NOR": [(1, 2)]}
        merge(base, {"NOR": [(2, 1)]})
        assert base["NOR"] == [(1, 2), (2, 1)]

    def test_a_later_value_replaces_an_earlier_one(self):
        base = {"NOR": [(1, 5)]}
        merge(base, {"NOR": [(1, 2)]})
        assert base["NOR"] == [(1, 2)]

    def test_brings_in_a_new_driver(self):
        base = {}
        merge(base, {"VER": [(1, 1)]})
        assert base == {"VER": [(1, 1)]}


class TestQueries:
    @pytest.fixture
    def history(self):
        return {"NOR": [(1, 2), (2, 2), (3, 1)], "VER": [(1, 1), (3, 2)]}

    def test_positions_at_a_lap(self, history):
        assert positions_at(history, 2) == {"NOR": 2, "VER": 1}

    def test_positions_carry_forward_when_a_lap_is_missing(self, history):
        # VER has no entry for lap 2, so lap 1 still stands.
        assert positions_at(history, 2)["VER"] == 1

    def test_nothing_before_the_first_lap(self, history):
        assert positions_at(history, 0) == {}

    def test_places_gained_over_the_session(self, history):
        assert places_gained(history) == {"NOR": 1, "VER": -1}

    def test_a_single_lap_yields_no_movement(self):
        assert places_gained({"NOR": [(1, 5)]}) == {}


class TestPayload:
    def test_converts_to_json_friendly_lists(self):
        assert to_payload({"NOR": [(1, 2)]}) == {"NOR": [[1, 2]]}
