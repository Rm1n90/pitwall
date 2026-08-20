"""Tests for the track elevation profile.

The position feed carries a Z channel: absolute altitude in tenths of a
metre, with gaps where the feed dropped out. Turning that into something a
renderer can use means filling the gaps, smoothing the noise, and rebasing
so the lowest point of the circuit sits at zero.
"""

import numpy as np
import pytest

from src.lib.elevation import (
    TENTHS_PER_METRE, fill_gaps, rebase, smooth, to_metres,
)


class TestToMetres:
    def test_converts_tenths_of_a_metre(self):
        assert to_metres(np.array([2390.0]))[0] == pytest.approx(239.0)

    def test_the_scale_matches_the_feed(self):
        assert TENTHS_PER_METRE == 10.0

    def test_missing_samples_become_nan(self):
        # The feed writes zero when it has no altitude, and a circuit is
        # never at sea level.
        out = to_metres(np.array([0.0, 2390.0]))
        assert np.isnan(out[0])
        assert out[1] == pytest.approx(239.0)


class TestFillGaps:
    def test_a_gap_is_interpolated_from_its_neighbours(self):
        filled = fill_gaps(np.array([10.0, np.nan, 20.0]))
        assert filled[1] == pytest.approx(15.0)

    def test_a_run_of_gaps_is_interpolated(self):
        filled = fill_gaps(np.array([0.0, np.nan, np.nan, np.nan, 40.0]))
        assert filled.tolist() == pytest.approx([0.0, 10.0, 20.0, 30.0, 40.0])

    def test_a_gap_at_the_start_wraps_around_the_lap(self):
        # A circuit is a loop, so the point before the first is the last.
        filled = fill_gaps(np.array([np.nan, 10.0, 20.0, 30.0]))
        assert np.isfinite(filled[0])
        assert 20.0 <= filled[0] <= 30.0

    def test_a_gap_at_the_end_wraps_around_the_lap(self):
        filled = fill_gaps(np.array([10.0, 20.0, 30.0, np.nan]))
        assert np.isfinite(filled[-1])

    def test_all_gaps_give_a_flat_profile(self):
        # Better a flat circuit than a crash.
        filled = fill_gaps(np.array([np.nan, np.nan, np.nan]))
        assert np.all(filled == 0.0)

    def test_a_profile_without_gaps_is_unchanged(self):
        original = np.array([1.0, 2.0, 3.0])
        assert fill_gaps(original).tolist() == [1.0, 2.0, 3.0]


class TestSmooth:
    def test_a_spike_is_flattened(self):
        noisy = np.array([10.0, 10.0, 40.0, 10.0, 10.0] * 6)
        assert smooth(noisy, window=5).max() < 40.0

    def test_the_overall_shape_survives(self):
        # A real climb must not be smoothed away. A circuit is a loop, so
        # the profile has to come back to where it started: a straight ramp
        # would be a cliff at the start line, and smoothing it flat there is
        # the right thing to do.
        angle = np.linspace(0.0, 2 * np.pi, 200, endpoint=False)
        hill = 15.0 * (1.0 - np.cos(angle))
        out = smooth(hill, window=9)
        assert out.max() - out.min() > 25.0
        assert abs(float(np.argmax(out)) - float(np.argmax(hill))) < 5

    def test_smoothing_wraps_around_the_lap(self):
        # The start line is not a discontinuity.
        loop = np.concatenate([np.zeros(50), np.zeros(50)])
        loop[0] = 10.0
        out = smooth(loop, window=5)
        assert out[-1] > 0.0

    def test_the_length_is_unchanged(self):
        assert len(smooth(np.zeros(37), window=5)) == 37

    def test_a_window_of_one_changes_nothing(self):
        values = np.array([1.0, 9.0, 1.0])
        assert smooth(values, window=1).tolist() == [1.0, 9.0, 1.0]


class TestRebase:
    def test_the_lowest_point_becomes_zero(self):
        out = rebase(np.array([204.1, 220.0, 239.1]))
        assert out.min() == pytest.approx(0.0)

    def test_the_range_is_preserved(self):
        out = rebase(np.array([204.1, 239.1]))
        assert out.max() == pytest.approx(35.0)

    def test_a_flat_circuit_stays_flat(self):
        out = rebase(np.array([100.0, 100.0]))
        assert out.tolist() == [0.0, 0.0]
