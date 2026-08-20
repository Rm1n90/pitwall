"""Tests for building the circuit mesh."""

import numpy as np
import pytest

from src.render.scene3d.mesh import (
    FEED_UNITS_PER_METRE, ribbon, surface_normals, to_world,
)


def circle(points=64, radius=1000.0):
    angle = np.linspace(0.0, 2 * np.pi, points, endpoint=False)
    return radius * np.cos(angle), radius * np.sin(angle)


class TestToWorld:
    """The feed measures the ground in tenths of a metre, and calls the
    ground plane X/Y with altitude in Z. World space is metres, Y-up."""

    def test_the_ground_plane_converts_to_metres(self):
        world = to_world(np.array([1000.0]), np.array([2000.0]),
                         np.array([0.0]))
        assert world[0][0] == pytest.approx(100.0)
        assert world[0][2] == pytest.approx(200.0)

    def test_the_scale_matches_the_feed(self):
        assert FEED_UNITS_PER_METRE == 10.0

    def test_elevation_becomes_the_up_axis(self):
        world = to_world(np.array([0.0]), np.array([0.0]), np.array([33.8]))
        assert world[0][1] == pytest.approx(33.8)

    def test_elevation_can_be_exaggerated(self):
        # Thirty metres across a kilometre of circuit is real but hard to
        # read, so the view is allowed to overstate it.
        world = to_world(np.array([0.0]), np.array([0.0]), np.array([10.0]),
                         elevation_scale=3.0)
        assert world[0][1] == pytest.approx(30.0)


class TestRibbon:
    def test_there_are_two_vertices_per_centreline_point(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        assert len(mesh.vertices) == 128

    def test_the_pair_is_a_track_width_apart(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        left, right = mesh.vertices[0], mesh.vertices[1]
        assert np.linalg.norm(left - right) == pytest.approx(15.0, abs=0.1)

    def test_the_ribbon_closes_into_a_loop(self):
        # The last segment has to join the first, or the circuit has a gap
        # across the start line.
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        assert mesh.indices.max() == len(mesh.vertices) - 1
        assert len(mesh.indices) == 64 * 6

    def test_the_surface_follows_the_elevation(self):
        x, y = circle(64)
        elevation = np.linspace(0.0, 30.0, 64)
        mesh = ribbon(x, y, elevation, width_m=15.0, elevation_scale=1.0)
        heights = mesh.vertices[:, 1]
        assert heights.max() == pytest.approx(30.0, abs=0.5)
        assert heights.min() == pytest.approx(0.0, abs=0.5)

    def test_both_edges_of_a_segment_sit_at_the_same_height(self):
        # Otherwise the track is banked everywhere by accident.
        x, y = circle(64)
        mesh = ribbon(x, y, np.linspace(0.0, 30.0, 64), width_m=15.0)
        assert mesh.vertices[0][1] == pytest.approx(mesh.vertices[1][1])

    def test_the_centre_of_the_ribbon_follows_the_centreline(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        middle = (mesh.vertices[0] + mesh.vertices[1]) / 2
        assert middle[0] == pytest.approx(x[0] / FEED_UNITS_PER_METRE, abs=0.1)
        assert middle[2] == pytest.approx(y[0] / FEED_UNITS_PER_METRE, abs=0.1)

    def test_the_distance_along_the_lap_is_recorded(self):
        # Used to lay markings and kerbs along the surface.
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        assert mesh.along.shape == (128,)
        assert mesh.along.min() == pytest.approx(0.0)
        assert mesh.along.max() > 0.0

    def test_which_side_of_the_track_each_vertex_is_on(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        assert set(np.unique(mesh.side)) == {-1.0, 1.0}

    def test_a_two_point_track_is_not_a_circuit(self):
        with pytest.raises(ValueError):
            ribbon(np.array([0.0, 1.0]), np.array([0.0, 1.0]),
                   np.zeros(2), width_m=15.0)


class TestNormals:
    def test_the_surface_faces_up_whichever_way_the_circuit_runs(self):
        # Half the calendar runs anticlockwise, which reverses the winding.
        x, y = circle(64)
        clockwise = ribbon(x[::-1], y[::-1], np.zeros(64), width_m=15.0)
        normals = surface_normals(clockwise.vertices, clockwise.indices)
        assert np.allclose(normals[:, 1], 1.0, atol=0.05)

    def test_a_flat_track_faces_straight_up(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.zeros(64), width_m=15.0)
        normals = surface_normals(mesh.vertices, mesh.indices)
        assert np.allclose(normals[:, 1], 1.0, atol=0.05)

    def test_normals_are_unit_length(self):
        x, y = circle(64)
        mesh = ribbon(x, y, np.linspace(0, 30, 64), width_m=15.0)
        normals = surface_normals(mesh.vertices, mesh.indices)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-5)

    def test_a_slope_tilts_the_normal(self):
        x, y = circle(64)
        climbing = ribbon(x, y, np.linspace(0.0, 200.0, 64), width_m=15.0)
        normals = surface_normals(climbing.vertices, climbing.indices)
        assert normals[:, 1].min() < 0.999


class TestResample:
    """The reference line from a telemetry lap is not fit to build from.

    Most of its points sit on top of each other and a few are hundreds of
    metres apart. Consecutive duplicates give no direction, so the
    perpendicular is arbitrary and the surface folds inside out.
    """

    def test_duplicate_points_are_removed(self):
        from src.render.scene3d.mesh import resample_closed
        x, y = circle(40)
        # Repeat every point three times, as the feed does.
        x, y = np.repeat(x, 3), np.repeat(y, 3)
        out_x, out_y = resample_closed(x, y, spacing_m=10.0)

        step = np.hypot(np.diff(out_x), np.diff(out_y))
        assert step.min() > 1.0

    def test_the_points_come_out_evenly_spaced(self):
        from src.render.scene3d.mesh import resample_closed
        x, y = circle(40)
        out_x, out_y = resample_closed(x, y, spacing_m=10.0)

        step = np.hypot(np.diff(out_x), np.diff(out_y)) / FEED_UNITS_PER_METRE
        assert step.std() < 0.5
        assert abs(step.mean() - 10.0) < 1.5

    def test_the_shape_is_kept(self):
        from src.render.scene3d.mesh import resample_closed
        x, y = circle(64, radius=1000.0)
        out_x, out_y = resample_closed(x, y, spacing_m=5.0)

        radius = np.hypot(out_x, out_y)
        assert abs(radius.mean() - 1000.0) < 12.0

    def test_the_loop_stays_closed(self):
        from src.render.scene3d.mesh import resample_closed
        x, y = circle(64)
        out_x, out_y = resample_closed(x, y, spacing_m=10.0)

        # The gap from the last point back to the first is one normal step.
        closing = np.hypot(out_x[0] - out_x[-1], out_y[0] - out_y[-1])
        typical = np.median(np.hypot(np.diff(out_x), np.diff(out_y)))
        assert closing < typical * 2.0

    def test_a_long_gap_is_bridged(self):
        from src.render.scene3d.mesh import resample_closed
        x = np.array([0.0, 100.0, 5000.0, 5100.0, 0.0])
        y = np.array([0.0, 0.0, 0.0, 500.0, 500.0])
        out_x, out_y = resample_closed(x, y, spacing_m=20.0)

        step = np.hypot(np.diff(out_x), np.diff(out_y)) / FEED_UNITS_PER_METRE
        assert step.max() < 40.0

    def test_a_line_that_is_all_one_point_is_returned_as_is(self):
        from src.render.scene3d.mesh import resample_closed
        x = np.zeros(10)
        y = np.zeros(10)
        out_x, out_y = resample_closed(x, y)
        assert len(out_x) == len(x)

    def test_resampling_gives_a_ribbon_that_does_not_fold(self):
        # Every segment of a clean ribbon should have a sane area; a folded
        # one collapses to nothing or turns inside out.
        from src.render.scene3d.mesh import resample_closed
        x, y = circle(40)
        x, y = np.repeat(x, 3), np.repeat(y, 3)
        clean_x, clean_y = resample_closed(x, y, spacing_m=8.0)
        mesh = ribbon(clean_x, clean_y, np.zeros(len(clean_x)), width_m=15.0)

        left = mesh.vertices[0::2]
        right = mesh.vertices[1::2]
        widths = np.linalg.norm(left - right, axis=1)
        assert widths.min() > 14.0 and widths.max() < 16.0


class TestResampleWithValues:
    def test_the_value_follows_its_point_around_the_lap(self):
        from src.render.scene3d.mesh import resample_with_values
        x, y = circle(64)
        # Elevation that rises and falls once around the loop.
        angle = np.linspace(0.0, 2 * np.pi, 64, endpoint=False)
        elevation = 20.0 * (1.0 - np.cos(angle))

        new_x, new_y, new_elevation = resample_with_values(
            x, y, elevation, spacing_m=8.0)

        assert len(new_elevation) == len(new_x)
        assert new_elevation.max() == pytest.approx(elevation.max(), abs=1.0)
        assert new_elevation.min() == pytest.approx(elevation.min(), abs=1.0)

    def test_the_high_point_stays_in_the_same_place(self):
        from src.render.scene3d.mesh import resample_with_values
        x, y = circle(64)
        elevation = np.zeros(64)
        elevation[16] = 30.0

        new_x, new_y, new_elevation = resample_with_values(
            x, y, elevation, spacing_m=8.0)

        peak = int(np.argmax(new_elevation))
        assert np.hypot(new_x[peak] - x[16], new_y[peak] - y[16]) < 80.0

    def test_a_mismatched_value_array_is_ignored(self):
        from src.render.scene3d.mesh import resample_with_values
        x, y = circle(64)
        _x, _y, values = resample_with_values(x, y, np.zeros(5))
        assert np.all(values == 0.0)
