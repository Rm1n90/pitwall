"""Tests for working out which stretch of track is under a flag."""

import pytest

from src.lib.flag_sectors import (
    DEFAULT_DURATION_S,
    active_flags,
    build_sector_flags,
    marshal_sectors_from_circuit_info,
)


def _message(time, flag, sector, message=""):
    return {"time": time, "flag": flag, "sector": sector, "message": message}


class TestBuildSectorFlags:
    def test_pairs_a_yellow_with_its_clear(self):
        periods = build_sector_flags([
            _message(100.0, "YELLOW", "19"),
            _message(160.0, "CLEAR", "19"),
        ])
        assert periods == [{"sector": 19, "flag": "YELLOW",
                            "start": 100.0, "end": 160.0}]

    def test_tracks_several_sectors_at_once(self):
        periods = build_sector_flags([
            _message(100.0, "YELLOW", "8"),
            _message(100.0, "YELLOW", "9"),
            _message(120.0, "CLEAR", "8"),
            _message(130.0, "CLEAR", "9"),
        ])
        assert {p["sector"]: p["end"] for p in periods} == {8: 120.0, 9: 130.0}

    def test_a_double_yellow_upgrades_the_existing_caution(self):
        periods = build_sector_flags([
            _message(100.0, "YELLOW", "6"),
            _message(120.0, "DOUBLE YELLOW", "6"),
            _message(200.0, "CLEAR", "6"),
        ])
        assert len(periods) == 1
        assert periods[0]["flag"] == "DOUBLE YELLOW"
        assert periods[0]["start"] == 100.0

    def test_an_uncleared_caution_does_not_last_forever(self):
        periods = build_sector_flags([_message(100.0, "YELLOW", "3")])
        assert periods[0]["end"] == 100.0 + DEFAULT_DURATION_S

    def test_messages_are_ordered_before_pairing(self):
        periods = build_sector_flags([
            _message(160.0, "CLEAR", "19"),
            _message(100.0, "YELLOW", "19"),
        ])
        assert periods[0]["end"] == 160.0

    def test_messages_without_a_sector_are_ignored(self):
        assert build_sector_flags([
            _message(10.0, "YELLOW", None),
            _message(20.0, "CHEQUERED", ""),
        ]) == []

    def test_a_green_flag_also_clears(self):
        periods = build_sector_flags([
            _message(100.0, "YELLOW", "4"),
            _message(150.0, "GREEN", "4"),
        ])
        assert periods[0]["end"] == 150.0

    def test_no_messages_is_not_an_error(self):
        assert build_sector_flags([]) == []
        assert build_sector_flags(None) == []


class TestActiveFlags:
    @pytest.fixture
    def periods(self):
        return build_sector_flags([
            _message(100.0, "YELLOW", "6"),
            _message(200.0, "CLEAR", "6"),
        ])

    def test_is_active_within_the_period(self, periods):
        assert len(active_flags(periods, 150.0)) == 1

    def test_is_not_active_before_or_after(self, periods):
        assert active_flags(periods, 50.0) == []
        assert active_flags(periods, 250.0) == []

    def test_the_boundaries_count_as_active(self, periods):
        assert active_flags(periods, 100.0) and active_flags(periods, 200.0)


class TestMarshalSectors:
    def test_reads_numbered_positions(self):
        import pandas as pd

        class _Info:
            marshal_sectors = pd.DataFrame({
                "X": [1.0, 2.0], "Y": [3.0, 4.0], "Number": [2, 1]})

        # Sorted, so sector 1 comes first.
        assert marshal_sectors_from_circuit_info(_Info()) == \
            [(1, 2.0, 4.0), (2, 1.0, 3.0)]

    def test_missing_information_is_not_an_error(self):
        class _Empty:
            marshal_sectors = None

        assert marshal_sectors_from_circuit_info(_Empty()) == []
