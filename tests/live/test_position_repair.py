"""Tests for reconstructing live positions when the feed stalls."""

import numpy as np
import pytest

from src.lib.track_geometry import TrackLine
from src.live.state import DriverSamples

RADIUS = 1000.0
SPEED_KMH = 180.0


@pytest.fixture
def circle():
    angles = np.linspace(0, 2 * np.pi, 600)
    return TrackLine(RADIUS * np.cos(angles), RADIUS * np.sin(angles))


def _samples_with_gap(circle, gap_s):
    """Two position samples ``gap_s`` apart, as a stalled feed would give."""
    samples = DriverSamples()
    units_per_s = SPEED_KMH / 3.6 * 10.0
    start_arc = 0.0
    end_arc = start_arc + units_per_s * gap_s

    x0, y0 = circle.point_at(start_arc)
    x1, y1 = circle.point_at(end_arc)
    samples.add_position(0.0, x0, y0, True)
    samples.add_position(gap_s, x1, y1, True)
    samples.add_car(0.0, {"speed": SPEED_KMH})
    samples.add_car(gap_s, {"speed": SPEED_KMH})
    return samples


class TestShortGaps:
    def test_a_healthy_feed_is_interpolated_normally(self, circle):
        samples = _samples_with_gap(circle, 0.24)
        with_line = samples.position_at(0.12, circle)
        without_line = samples.position_at(0.12)
        assert with_line == without_line


class TestStalledFeed:
    def test_the_car_follows_the_track_across_a_long_gap(self, circle):
        samples = _samples_with_gap(circle, 2.0)

        x, y, _ = samples.position_at(1.0, circle)

        # Straight-line interpolation would cut the chord across the infield.
        assert np.hypot(x, y) == pytest.approx(RADIUS, rel=0.05)

    def test_straight_line_interpolation_would_cut_the_corner(self, circle):
        samples = _samples_with_gap(circle, 2.0)

        x, y, _ = samples.position_at(1.0)

        assert np.hypot(x, y) < RADIUS * 0.95

    def test_the_car_keeps_moving_through_the_gap(self, circle):
        samples = _samples_with_gap(circle, 2.0)
        points = [samples.position_at(t, circle)[:2]
                  for t in (0.4, 0.8, 1.2, 1.6)]
        steps = [np.hypot(b[0] - a[0], b[1] - a[1])
                 for a, b in zip(points, points[1:])]
        assert min(steps) > 0

    def test_progress_through_the_gap_is_monotonic(self, circle):
        samples = _samples_with_gap(circle, 2.0)
        arcs = [circle.project(*samples.position_at(t, circle)[:2])[0]
                for t in np.linspace(0.1, 1.9, 12)]
        assert arcs == sorted(arcs)

    def test_a_stationary_car_stays_put(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        samples.add_position(0.0, x0, y0, True)
        samples.add_position(5.0, x0, y0, True)
        samples.add_car(0.0, {"speed": 0.0})
        samples.add_car(5.0, {"speed": 0.0})

        x, y, _ = samples.position_at(2.5, circle)
        assert (x, y) == (x0, y0)

    def test_refuses_to_move_a_car_further_than_its_speed_allows(self, circle):
        # The two anchors sit most of a lap apart, but at 40 km/h the car
        # cannot have covered that. Reconstructing anyway would fling it round
        # the circuit, so the reconstruction is abandoned.
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        x1, y1 = circle.point_at(circle.length * 0.8)
        samples.add_position(0.0, x0, y0, True)
        samples.add_position(2.0, x1, y1, True)
        samples.add_car(0.0, {"speed": 40.0})
        samples.add_car(2.0, {"speed": 40.0})

        assert samples.position_at(1.0, circle) == samples.position_at(1.0)

    def test_a_short_reconstruction_is_harmless(self, circle):
        # The opposite direction is safe: if the anchors are closer together
        # than the speed suggests, following the track just reproduces
        # something very close to the straight line anyway.
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        x1, y1 = circle.point_at(50.0)
        samples.add_position(0.0, x0, y0, True)
        samples.add_position(3.0, x1, y1, True)
        samples.add_car(0.0, {"speed": 300.0})
        samples.add_car(3.0, {"speed": 300.0})

        followed = samples.position_at(1.5, circle)
        straight = samples.position_at(1.5)
        assert np.hypot(followed[0] - straight[0],
                        followed[1] - straight[1]) < 5.0


class TestEdges:
    def test_no_samples_returns_nothing(self, circle):
        assert DriverSamples().position_at(1.0, circle) is None

    def test_before_the_first_sample_clamps(self, circle):
        samples = _samples_with_gap(circle, 2.0)
        assert samples.position_at(-5.0, circle)[:2] == \
            (samples.xs[0], samples.ys[0])

    def test_after_the_last_sample_clamps(self, circle):
        samples = _samples_with_gap(circle, 2.0)
        assert samples.position_at(99.0, circle)[:2] == \
            (samples.xs[-1], samples.ys[-1])

    def test_a_gap_without_telemetry_falls_back(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        x1, y1 = circle.point_at(1000.0)
        samples.add_position(0.0, x0, y0, True)
        samples.add_position(2.0, x1, y1, True)
        # No car data at all, so the speed cross-check cannot run.
        assert samples.position_at(1.0, circle) == samples.position_at(1.0)


class TestDeadReckoning:
    """When the feed has not located a car for longer than the render delay
    there is no later sample to interpolate towards, so the car is carried
    forward along the circuit instead of stopping dead."""

    def _stranded(self, circle, speed=SPEED_KMH, last_seen=0.0):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        samples.add_position(last_seen, x0, y0, True)
        for t in np.arange(last_seen, last_seen + 6.0, 0.25):
            samples.add_car(float(t), {"speed": speed})
        return samples

    def test_the_car_keeps_going_past_its_last_known_position(self, circle):
        samples = self._stranded(circle)

        x, y, _ = samples.position_at(2.0, circle)

        start = circle.point_at(0.0)
        assert np.hypot(x - start[0], y - start[1]) > 100

    def test_it_travels_roughly_the_right_distance(self, circle):
        samples = self._stranded(circle)

        x, y, _ = samples.position_at(2.0, circle)
        arc, _, _ = circle.project(x, y)

        expected = SPEED_KMH / 3.6 * 10.0 * 2.0
        assert arc == pytest.approx(expected, rel=0.1)

    def test_it_stays_on_the_track(self, circle):
        samples = self._stranded(circle)
        for t in (0.5, 1.0, 2.0, 3.0):
            x, y, _ = samples.position_at(t, circle)
            assert np.hypot(x, y) == pytest.approx(RADIUS, rel=0.05)

    def test_prediction_stops_after_the_horizon(self, circle):
        samples = self._stranded(circle)

        far = samples.position_at(30.0, circle)

        assert far[:2] == (samples.xs[-1], samples.ys[-1])

    def test_a_stopped_car_is_not_carried_forward(self, circle):
        # The speed channel is separate from the position feed, so a car that
        # has actually stopped must stay stopped.
        samples = self._stranded(circle, speed=0.0)

        x, y, _ = samples.position_at(2.0, circle)

        assert (x, y) == (samples.xs[-1], samples.ys[-1])

    def test_without_a_track_line_the_car_simply_holds_position(self, circle):
        samples = self._stranded(circle)
        assert samples.position_at(2.0)[:2] == (samples.xs[-1], samples.ys[-1])

    def test_no_telemetry_means_no_prediction(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        samples.add_position(0.0, x0, y0, True)

        assert samples.position_at(2.0, circle)[:2] == (x0, y0)


class TestRepeatedCoordinates:
    """A feed that has lost a car repeats its last coordinate. Recording those
    would disguise a multi-second stall as a healthy stream of samples."""

    def test_repeated_coordinates_are_not_stored(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        for t in (0.0, 0.25, 0.5, 0.75):
            samples.add_position(t, x0, y0, True)

        assert len(samples.times) == 1

    def test_real_movement_is_stored(self, circle):
        samples = DriverSamples()
        # 125 units per quarter second is 180 km/h, a plausible racing speed.
        for index, arc in enumerate((0.0, 125.0, 250.0)):
            x, y = circle.point_at(arc)
            samples.add_position(index * 0.25, x, y, True)

        assert len(samples.times) == 3

    def test_the_gap_stays_visible_after_a_stall(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        samples.add_position(0.0, x0, y0, True)
        for t in np.arange(0.25, 2.0, 0.25):      # feed repeats itself
            samples.add_position(float(t), x0, y0, True)
        x1, y1 = circle.point_at(1000.0)   # 100 m in 2 s, i.e. 180 km/h
        samples.add_position(2.0, x1, y1, True)

        # Two anchors two seconds apart, not nine that look healthy.
        assert list(samples.times) == [0.0, 2.0]

    def test_track_status_still_updates_while_stalled(self, circle):
        samples = DriverSamples()
        x0, y0 = circle.point_at(0.0)
        samples.add_position(0.0, x0, y0, True)
        samples.add_position(0.25, x0, y0, False)

        assert samples.on_track[-1] is False
