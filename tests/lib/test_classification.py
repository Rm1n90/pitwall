"""Tests for race classification and ordering.

Each test names the real failure it guards against; all three were observed in
the 2026 Hungarian Grand Prix data before the fix.
"""

import pytest

from src.lib.classification import (
    GRID_SLOT_SPACING_M,
    UNKNOWN_GRID_POSITION,
    DriverClassification,
    RaceClassification,
    assign_positions,
    enforce_monotonic,
    lap_one_progress,
    order_drivers,
    race_progress,
)

LAP_M = 4000.0


def _race(drivers=None, finish_time_s=None):
    return RaceClassification(drivers=drivers or {}, finish_time_s=finish_time_s)


def _driver(code, grid=1, final=None, finish=None, flag=False):
    return DriverClassification(code, grid, final, finish, flag)


class TestLapOneProgress:
    """The grid is spread over 150 m; lap-one distance starts at zero for all."""

    def test_pole_starts_on_the_timing_line(self):
        assert lap_one_progress(0.0, 1, LAP_M) == 0.0

    def test_the_rest_of_the_grid_starts_behind_pole(self):
        p20 = lap_one_progress(0.0, 20, LAP_M)
        assert p20 == pytest.approx(-19 * GRID_SLOT_SPACING_M / LAP_M)
        assert p20 < 0

    def test_grid_order_is_preserved_at_lights_out(self):
        starts = [lap_one_progress(0.0, slot, LAP_M) for slot in range(1, 21)]
        assert starts == sorted(starts, reverse=True)

    def test_everyone_converges_on_one_lap_at_the_line(self):
        for slot in (1, 10, 20):
            assert lap_one_progress(1.0, slot, LAP_M) == pytest.approx(1.0)

    def test_progress_increases_through_the_lap(self):
        values = [lap_one_progress(r / 10, 15, LAP_M) for r in range(11)]
        assert values == sorted(values)

    def test_an_unknown_grid_slot_still_produces_a_number(self):
        assert lap_one_progress(0.5, UNKNOWN_GRID_POSITION, LAP_M) < 0.5

    def test_a_zero_lap_length_does_not_divide_by_zero(self):
        assert lap_one_progress(0.4, 5, 0.0) == 0.4


class TestRaceProgress:
    def test_later_laps_are_lap_plus_fraction(self):
        assert race_progress(5, 0.25, 1, LAP_M) == pytest.approx(4.25)

    def test_lap_one_applies_the_grid_offset(self):
        assert race_progress(1, 0.0, 10, LAP_M) < 0

    def test_lap_numbers_below_one_are_treated_as_lap_one(self):
        assert race_progress(0, 0.5, 1, LAP_M) == \
            pytest.approx(lap_one_progress(0.5, 1, LAP_M))


class TestMonotonic:
    """Resampling can dip by a frame where lap and distance disagree."""

    def test_removes_backward_steps(self):
        assert enforce_monotonic([0.0, 1.0, 0.9, 2.0]) == [0.0, 1.0, 1.0, 2.0]

    def test_leaves_an_increasing_series_alone(self):
        assert enforce_monotonic([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]

    def test_handles_an_empty_series(self):
        assert enforce_monotonic([]) == []


class TestOrderingWhileRacing:
    def test_ranks_by_race_progress(self):
        order = order_drivers([("A", 10.5), ("B", 11.2), ("C", 9.9)], 100.0,
                              _race())
        assert order == ["B", "A", "C"]

    def test_a_retired_car_sinks_rather_than_being_promoted(self):
        # A retired car has a classified position, but it must not be used
        # while the race is running or it jumps to the front of the order.
        classification = _race(
            {"OUT": _driver("OUT", final=22, finish=500.0, flag=False),
             "LDR": _driver("LDR", final=1, finish=6000.0, flag=True)},
            finish_time_s=6000.0,
        )
        order = order_drivers([("OUT", 13.9), ("LDR", 35.2)], 3000.0,
                              classification)
        assert order == ["LDR", "OUT"]

    def test_positions_are_numbered_from_one(self):
        positions = assign_positions([("A", 1.0), ("B", 2.0)], 0.0, _race())
        assert positions == {"B": 1, "A": 2}


class TestOrderingAfterTheFlag:
    """Cool-down laps must not move anybody."""

    @pytest.fixture
    def settled(self):
        return _race(
            {"WIN": _driver("WIN", final=1, finish=6000.0, flag=True),
             "TWO": _driver("TWO", final=2, finish=6015.0, flag=True),
             "RET": _driver("RET", final=20, finish=900.0, flag=False)},
            finish_time_s=6000.0,
        )

    def test_uses_progress_before_the_winner_finishes(self, settled):
        order = order_drivers([("WIN", 69.8), ("TWO", 69.9)], 5999.0, settled)
        assert order == ["TWO", "WIN"]

    def test_official_result_takes_over_once_the_flag_falls(self, settled):
        # TWO is momentarily further round the cool-down lap, which is exactly
        # how the finishing order used to get scrambled.
        order = order_drivers([("WIN", 70.1), ("TWO", 70.4)], 6100.0, settled)
        assert order == ["WIN", "TWO"]

    def test_retired_cars_keep_their_classified_place(self, settled):
        order = order_drivers([("WIN", 70.1), ("TWO", 70.0), ("RET", 12.0)],
                              6100.0, settled)
        assert order == ["WIN", "TWO", "RET"]

    def test_unclassified_drivers_are_ranked_last_by_progress(self, settled):
        order = order_drivers(
            [("WIN", 70.1), ("GHOST", 5.0), ("OTHER", 9.0)], 6100.0, settled)
        assert order[0] == "WIN"
        assert order[1:] == ["OTHER", "GHOST"]


class TestRaceClassification:
    def test_is_not_settled_without_a_finish_time(self):
        assert _race().is_settled(10_000.0) is False

    def test_is_settled_only_from_the_finish_time(self):
        race = _race(finish_time_s=100.0)
        assert race.is_settled(99.9) is False
        assert race.is_settled(100.0) is True

    def test_unknown_drivers_return_none(self):
        assert _race().get("NOPE") is None
