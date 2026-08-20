"""Tests for the 3D camera.

World space is Y-up: X and Z are the ground plane, Y is elevation. The feed
gives X and Y on the ground with Z as altitude, so the mesh builder swaps
them; everything above that layer works in Y-up.
"""

import numpy as np
import pytest

from src.render.scene3d.camera import Camera3D


@pytest.fixture
def camera():
    return Camera3D(target=(0.0, 0.0, 0.0), distance=100.0,
                    yaw=0.0, pitch=0.0)


class TestPosition:
    def test_the_camera_sits_its_distance_from_the_target(self, camera):
        assert np.linalg.norm(camera.position()) == pytest.approx(100.0)

    def test_pitching_up_raises_the_camera(self, camera):
        camera.pitch = np.deg2rad(45.0)
        assert camera.position()[1] > 0.0

    def test_yaw_swings_the_camera_around(self, camera):
        start = camera.position()
        camera.yaw = np.deg2rad(90.0)
        assert not np.allclose(start, camera.position())
        assert np.linalg.norm(camera.position()) == pytest.approx(100.0)

    def test_the_camera_orbits_its_target(self):
        camera = Camera3D(target=(10.0, 5.0, -3.0), distance=50.0)
        offset = camera.position() - np.array([10.0, 5.0, -3.0])
        assert np.linalg.norm(offset) == pytest.approx(50.0)


class TestProjection:
    def test_the_target_lands_in_the_middle_of_the_screen(self, camera):
        screen, _depth, visible = camera.project(
            np.array([[0.0, 0.0, 0.0]]), 800, 600)
        assert visible[0]
        assert screen[0][0] == pytest.approx(400.0, abs=0.5)
        assert screen[0][1] == pytest.approx(300.0, abs=0.5)

    def test_something_behind_the_camera_is_not_visible(self, camera):
        # The camera looks from +Z towards the origin, so a point well
        # beyond it is behind.
        _screen, _depth, visible = camera.project(
            np.array([[0.0, 0.0, 500.0]]), 800, 600)
        assert not visible[0]

    def test_a_point_further_away_sits_nearer_the_centre(self, camera):
        near = camera.project(np.array([[10.0, 0.0, 0.0]]), 800, 600)[0][0][0]
        far = camera.project(np.array([[10.0, 0.0, -200.0]]), 800, 600)[0][0][0]
        assert abs(far - 400.0) < abs(near - 400.0)

    def test_depth_grows_with_distance(self, camera):
        _s, near, _v = camera.project(np.array([[0.0, 0.0, 50.0]]), 800, 600)
        _s, far, _v = camera.project(np.array([[0.0, 0.0, -50.0]]), 800, 600)
        assert far[0] > near[0]

    def test_many_points_project_at_once(self, camera):
        points = np.zeros((25, 3))
        screen, depth, visible = camera.project(points, 800, 600)
        assert screen.shape == (25, 2)
        assert depth.shape == (25,)
        assert visible.shape == (25,)

    def test_no_points_is_not_an_error(self, camera):
        screen, depth, visible = camera.project(np.zeros((0, 3)), 800, 600)
        assert len(screen) == 0 and len(depth) == 0 and len(visible) == 0


class TestControls:
    def test_orbiting_turns_the_camera(self, camera):
        camera.orbit(0.5, 0.0)
        assert camera.yaw == pytest.approx(0.5)

    def test_pitch_cannot_go_under_the_ground(self, camera):
        camera.orbit(0.0, -10.0)
        assert camera.pitch > 0.0

    def test_pitch_cannot_pass_straight_overhead(self, camera):
        camera.orbit(0.0, 10.0)
        assert camera.pitch < np.pi / 2

    def test_zooming_in_shortens_the_distance(self, camera):
        camera.zoom(0.5)
        assert camera.distance < 100.0

    def test_zoom_stops_before_the_camera_is_inside_the_track(self, camera):
        for _ in range(50):
            camera.zoom(0.5)
        assert camera.distance >= camera.min_distance

    def test_zoom_stops_before_the_circuit_is_a_speck(self, camera):
        for _ in range(50):
            camera.zoom(2.0)
        assert camera.distance <= camera.max_distance

    def test_the_camera_can_be_moved_to_follow_a_car(self, camera):
        camera.look_at((25.0, 3.0, -8.0))
        assert camera.target.tolist() == [25.0, 3.0, -8.0]


class TestMatrices:
    def test_the_view_projection_is_four_by_four(self, camera):
        assert camera.view_projection(4 / 3).shape == (4, 4)

    def test_the_matrix_is_ready_for_the_shader(self, camera):
        data = camera.view_projection_bytes(4 / 3)
        assert isinstance(data, bytes)
        assert len(data) == 16 * 4  # sixteen 32-bit floats


class TestFit:
    """Standing far enough back that the whole circuit is in view."""

    def test_a_bigger_circuit_needs_more_room(self, camera):
        camera.fit(500.0, 16 / 9)
        near = camera.distance
        camera.fit(1500.0, 16 / 9)
        assert camera.distance > near

    def test_the_circuit_actually_fits(self, camera):
        radius = 700.0
        camera.fit(radius, 16 / 9)
        camera.pitch = np.deg2rad(90.0)  # straight down, the tightest case

        # The far edge of the circuit has to land inside the viewport.
        edge = np.array([[radius, 0.0, 0.0], [-radius, 0.0, 0.0],
                         [0.0, 0.0, radius], [0.0, 0.0, -radius]])
        screen, _depth, visible = camera.project(edge, 1600, 900)
        assert visible.all()
        assert (screen[:, 0] >= 0).all() and (screen[:, 0] <= 1600).all()
        assert (screen[:, 1] >= 0).all() and (screen[:, 1] <= 900).all()

    def test_a_tall_window_needs_more_room_than_a_wide_one(self, camera):
        camera.fit(700.0, 16 / 9)
        wide = camera.distance
        camera.fit(700.0, 9 / 16)
        assert camera.distance > wide

    def test_fitting_respects_the_zoom_limits(self, camera):
        camera.fit(10_000_000.0, 16 / 9)
        assert camera.distance <= camera.max_distance


class TestFramePoints:
    """Framing the circuit exactly, rather than assuming it is a sphere."""

    def _oval(self, radius=700.0):
        angle = np.linspace(0.0, 2 * np.pi, 120, endpoint=False)
        return np.column_stack([radius * np.cos(angle),
                                np.zeros(120),
                                radius * 0.55 * np.sin(angle)])

    def test_every_point_ends_up_on_screen(self, camera):
        points = self._oval()
        camera.pitch = np.deg2rad(35.0)
        camera.frame_points(points, 1600, 900)

        screen, _depth, visible = camera.project(points, 1600, 900)
        assert visible.all()
        assert (screen[:, 0] >= 0).all() and (screen[:, 0] <= 1600).all()
        assert (screen[:, 1] >= 0).all() and (screen[:, 1] <= 900).all()

    def test_a_flat_shape_is_framed_tighter_than_its_bounding_sphere(self,
                                                                    camera):
        # An oval seen from above uses less of the view than a circle of the
        # same radius, and the camera should come in to suit.
        points = self._oval()
        camera.pitch = np.deg2rad(35.0)

        camera.fit(700.0, 16 / 9)
        by_radius = camera.distance
        camera.frame_points(points, 1600, 900)

        assert camera.distance < by_radius

    def test_framing_fills_a_useful_part_of_the_view(self, camera):
        points = self._oval()
        camera.frame_points(points, 1600, 900)

        screen, _d, _v = camera.project(points, 1600, 900)
        width_used = (screen[:, 0].max() - screen[:, 0].min()) / 1600
        assert width_used > 0.7

    def test_no_points_leaves_the_camera_alone(self, camera):
        before = camera.distance
        camera.frame_points(np.zeros((0, 3)), 1600, 900)
        assert camera.distance == before

    def test_framing_respects_the_zoom_limits(self, camera):
        camera.frame_points(self._oval(radius=5_000_000.0), 1600, 900)
        assert camera.distance <= camera.max_distance


class TestFramingAroundPanels:
    """Panels cover the sides and the top, so the circuit has to fit between."""

    def _oval(self, radius=700.0):
        angle = np.linspace(0.0, 2 * np.pi, 120, endpoint=False)
        return np.column_stack([radius * np.cos(angle),
                                np.zeros(120),
                                radius * 0.55 * np.sin(angle)])

    def test_leaving_room_for_panels_pulls_the_camera_back(self, camera):
        points = self._oval()
        camera.frame_points(points, 1600, 900)
        full = camera.distance

        camera.frame_points(points, 1600, 900, fill=(0.55, 0.75))
        assert camera.distance > full

    def test_the_circuit_stays_inside_the_space_it_was_given(self, camera):
        points = self._oval()
        camera.frame_points(points, 1600, 900, fill=(0.55, 0.75))

        screen, _depth, _visible = camera.project(points, 1600, 900)
        assert (np.abs(screen[:, 0] / 1600 * 2 - 1) <= 0.56).all()
        assert (np.abs(screen[:, 1] / 900 * 2 - 1) <= 0.76).all()
