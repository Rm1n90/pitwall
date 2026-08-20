"""Tests for parsing published pit stop times."""

import pytest

from src.lib.pit_stops import (
    MAX_STATIONARY_S,
    PitStop,
    parse_pit_stop_series,
    stops_by_code,
)


def _payload(entries):
    return {"PitTimes": entries}


class TestParsing:
    def test_reads_a_stop(self):
        stops = parse_pit_stop_series(_payload({"18": [
            {"Timestamp": "2026-07-26T13:15:41Z",
             "PitStop": {"RacingNumber": "18", "PitStopTime": "2.1",
                         "PitLaneTime": "21.789", "Lap": "8"}},
        ]}))
        assert stops["18"] == [PitStop(lap=8, stationary_s=2.1,
                                       pit_lane_s=21.789)]

    def test_keeps_stops_in_order(self):
        stops = parse_pit_stop_series(_payload({"44": [
            {"PitStop": {"PitStopTime": "2.6", "Lap": "13"}},
            {"PitStop": {"PitStopTime": "2.4", "Lap": "30"}},
        ]}))
        assert [s.lap for s in stops["44"]] == [13, 30]

    def test_accepts_a_live_update_keyed_by_index(self):
        # The stream sends increments as a dict rather than a list.
        stops = parse_pit_stop_series(_payload({"1": {
            "0": {"PitStop": {"PitStopTime": "2.3", "Lap": "20"}},
        }}))
        assert stops["1"][0].stationary_s == 2.3

    def test_accepts_a_record_without_the_wrapper(self):
        stops = parse_pit_stop_series(_payload({"1": [
            {"PitStopTime": "2.2", "PitLaneTime": "21.0", "Lap": "5"},
        ]}))
        assert stops["1"][0].stationary_s == 2.2


class TestBadData:
    def test_an_absurd_stationary_time_is_dropped(self):
        stops = parse_pit_stop_series(_payload({"1": [
            {"PitStop": {"PitStopTime": str(MAX_STATIONARY_S + 10),
                         "Lap": "5"}},
        ]}))
        assert stops["1"][0].stationary_s is None
        assert stops["1"][0].lap == 5

    def test_missing_values_become_none(self):
        stops = parse_pit_stop_series(_payload({"1": [{"PitStop": {}}]}))
        assert stops["1"] == [PitStop(lap=None, stationary_s=None,
                                      pit_lane_s=None)]

    @pytest.mark.parametrize("payload", [
        None, {}, {"PitTimes": None}, {"PitTimes": []}, "nonsense",
    ])
    def test_unusable_payloads_yield_nothing(self, payload):
        assert parse_pit_stop_series(payload) == {}

    def test_skips_records_that_are_not_objects(self):
        stops = parse_pit_stop_series(_payload({"1": ["nope", 5]}))
        assert stops.get("1", []) == []


class TestKeyingByDriver:
    def test_maps_car_numbers_to_driver_codes(self):
        class _Session:
            @staticmethod
            def get_driver(number):
                return {"Abbreviation": {"1": "NOR", "44": "HAM"}[number]}

        by_code = stops_by_code(_Session(), {
            "1": [PitStop(1, 2.0, 20.0)], "44": [PitStop(2, 2.5, 21.0)]})
        assert set(by_code) == {"NOR", "HAM"}

    def test_an_unknown_car_number_is_skipped(self):
        class _Session:
            @staticmethod
            def get_driver(number):
                raise KeyError(number)

        assert stops_by_code(_Session(), {"99": [PitStop(1, 2.0, 20.0)]}) == {}
