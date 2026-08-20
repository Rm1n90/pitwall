"""Tests for the gap chart's axis scaling."""

import pytest

pytest.importorskip("PySide6", reason="PySide6 is an optional dependency")

from src.insights.gap_chart_window import (  # noqa: E402
    AXIS_DIVISIONS,
    axis_maximum,
)


class TestAxisMaximum:
    """The axis is drawn in six divisions, so its top must divide by six.

    Otherwise the labels come out as +43s and +85s, which nobody reads.
    """

    def test_a_close_race_gets_a_tight_axis(self):
        assert axis_maximum(4.0) == 6.0

    def test_the_axis_always_covers_the_widest_gap(self):
        for gap in (0.5, 7.0, 31.0, 119.0, 255.0, 1000.0):
            assert axis_maximum(gap) >= gap

    def test_every_division_lands_on_a_whole_second(self):
        for gap in (4.0, 31.0, 255.0, 1000.0):
            step = axis_maximum(gap) / AXIS_DIVISIONS
            assert step == int(step)

    def test_a_gap_bigger_than_the_ladder_still_scales(self):
        # Two cars several laps apart late in a long race.
        assert axis_maximum(2500.0) >= 2500.0

    def test_the_axis_never_collapses_to_nothing(self):
        assert axis_maximum(0.0) > 0
