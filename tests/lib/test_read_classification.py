"""Tests for reading the official classification out of a FastF1 session."""

import pandas as pd
import pytest

from src.lib.classification import UNKNOWN_GRID_POSITION, read_classification


class _FakeSession:
    """Minimal stand-in for a loaded FastF1 session."""

    def __init__(self, results, laps):
        self.results = results
        self.laps = laps


def _results(rows):
    return pd.DataFrame(rows, columns=[
        "Abbreviation", "GridPosition", "Position", "ClassifiedPosition",
    ])


def _laps(rows):
    return pd.DataFrame(rows, columns=["Driver", "LapNumber", "Time"])


@pytest.fixture
def session():
    results = _results([
        ["NOR", 1.0, 1.0, "1"],
        ["VER", 4.0, 2.0, "2"],
        ["PIA", 3.0, 20.0, "R"],     # retired
        ["PIT", 0.0, 19.0, "19"],    # started from the pit lane
    ])
    laps = _laps([
        ["NOR", 1.0, pd.Timedelta(seconds=3400)],
        ["NOR", 70.0, pd.Timedelta(seconds=9244)],
        ["VER", 70.0, pd.Timedelta(seconds=9259)],
        ["PIA", 14.0, pd.Timedelta(seconds=4500)],
        ["PIT", 69.0, pd.Timedelta(seconds=9300)],
    ])
    return _FakeSession(results, laps)


class TestReadClassification:
    def test_reads_grid_positions(self, session):
        race = read_classification(session)
        assert race.get("NOR").grid_position == 1
        assert race.get("VER").grid_position == 4

    def test_a_pit_lane_start_goes_to_the_back(self, session):
        assert read_classification(session).get("PIT").grid_position == \
            UNKNOWN_GRID_POSITION

    def test_reads_final_positions(self, session):
        race = read_classification(session)
        assert race.get("NOR").final_position == 1
        assert race.get("PIA").final_position == 20

    def test_distinguishes_finishers_from_retirements(self, session):
        race = read_classification(session)
        assert race.get("NOR").took_flag is True
        assert race.get("PIA").took_flag is False

    def test_finish_times_come_from_the_last_lap(self, session):
        race = read_classification(session)
        assert race.get("NOR").finish_time_s == 9244
        assert race.get("PIA").finish_time_s == 4500

    def test_applies_the_replay_time_offset(self, session):
        race = read_classification(session, time_offset_s=3248.0)
        assert race.get("NOR").finish_time_s == pytest.approx(5996.0)

    def test_the_race_is_settled_when_the_winner_finishes(self, session):
        race = read_classification(session, time_offset_s=3248.0)
        assert race.finish_time_s == pytest.approx(5996.0)
        assert race.is_settled(5995.0) is False
        assert race.is_settled(5997.0) is True

    def test_a_retired_leader_does_not_settle_the_race(self):
        # Guards against a retirement being mistaken for the winner's flag.
        session = _FakeSession(
            _results([["AAA", 1.0, 1.0, "R"]]),
            _laps([["AAA", 5.0, pd.Timedelta(seconds=600)]]),
        )
        assert read_classification(session).finish_time_s is None


class TestMissingData:
    def test_survives_a_session_without_results(self):
        session = _FakeSession(pd.DataFrame(), pd.DataFrame())
        race = read_classification(session)
        assert race.drivers == {}
        assert race.finish_time_s is None

    def test_survives_a_session_with_no_results_attribute(self):
        class _Bare:
            pass
        race = read_classification(_Bare())
        assert race.drivers == {}

    def test_skips_rows_with_unusable_values(self):
        session = _FakeSession(
            _results([["", 1.0, 1.0, "1"], ["OKA", None, None, "2"]]),
            _laps([["OKA", None, None]]),
        )
        race = read_classification(session)
        assert "" not in race.drivers
        assert race.get("OKA").grid_position == UNKNOWN_GRID_POSITION
        assert race.get("OKA").final_position is None
