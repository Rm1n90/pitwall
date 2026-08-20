"""Tests for placing cars on the circuit surface."""

import numpy as np
import pytest

from src.render.scene3d.surface import TrackSurface


def circle(points=72, radius=1000.0):
    angle = np.linspace(0.0, 2 * np.pi, points, endpoint=False)
    return radius * np.cos(angle), radius * np.sin(angle)


@pytest.fixture
def flat():
    x, y = circle()
    return TrackSurface(x, y, np.zeros(len(x)))


class TestPlacement:
    def test_a_car_sits_at_the_height_of_the_track_under_it(self):
        x, y = circle()
        elevation = np.full(len(x), 20.0)
        surface = TrackSurface(x, y, elevation)

        world, _heading = surface.place([x[0]], [y[0]])
        assert world[0][1] == pytest.approx(20.0)

    def test_elevation_can_be_exaggerated(self):
        x, y = circle()
        surface = TrackSurface(x, y, np.full(len(x), 10.0),
                               elevation_scale=3.0)
        world, _heading = surface.place([x[0]], [y[0]])
        assert world[0][1] == pytest.approx(30.0)

    def test_the_ground_position_converts_to_metres(self, flat):
        world, _heading = flat.place([1000.0], [0.0])
        assert world[0][0] == pytest.approx(100.0)

    def test_a_car_between_points_takes_the_nearer_one(self):
        x = np.array([0.0, 100.0, 200.0, 300.0])
        y = np.array([0.0, 0.0, 0.0, 0.0])
        surface = TrackSurface(x, y, np.array([0.0, 5.0, 10.0, 15.0]))

        world, _heading = surface.place([96.0], [0.0])
        assert world[0][1] == pytest.approx(5.0)

    def test_the_whole_field_is_placed_at_once(self, flat):
        x, y = circle()
        world, heading = flat.place(x[:22], y[:22])
        assert world.shape == (22, 3)
        assert heading.shape == (22,)

    def test_an_empty_field_places_nothing(self, flat):
        world, heading = flat.place([], [])
        assert len(world) == 0 and len(heading) == 0


class TestHeading:
    def test_cars_face_along_the_track(self):
        # Around a circle every car has a different heading, and they turn
        # steadily rather than jumping about.
        x, y = circle(72)
        surface = TrackSurface(x, y, np.zeros(72))
        _world, heading = surface.place(x, y)

        turns = np.diff(np.unwrap(heading))
        assert np.allclose(turns, turns[0], atol=1e-6)

    def test_a_straight_gives_a_constant_heading(self):
        x = np.linspace(0.0, 1000.0, 20)
        y = np.zeros(20)
        surface = TrackSurface(x, y, np.zeros(20))
        _world, heading = surface.place(x[5:15], y[5:15])

        assert np.allclose(heading, heading[0], atol=1e-9)


class TestExtent:
    def test_the_centre_is_in_the_middle_of_the_circuit(self, flat):
        centre = flat.centre_world()
        assert centre[0] == pytest.approx(0.0, abs=1.0)
        assert centre[2] == pytest.approx(0.0, abs=1.0)

    def test_the_radius_covers_the_circuit(self, flat):
        # A circle of a thousand feed units is a hundred metres across.
        assert flat.radius_world() == pytest.approx(100.0, abs=1.0)

    def test_a_track_of_one_point_is_not_a_circuit(self):
        with pytest.raises(ValueError):
            TrackSurface([0.0], [0.0], [0.0])
