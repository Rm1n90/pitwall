"""Tests for the car model."""

import numpy as np
import pytest

from src.render.scene3d.car_mesh import (
    CAR_LENGTH_M, CAR_WIDTH_M, build, interleaved,
)


@pytest.fixture
def car():
    return build()


class TestShape:
    def test_every_vertex_has_a_normal(self, car):
        vertices, normals, _indices = car
        assert len(vertices) == len(normals)

    def test_the_indices_describe_whole_triangles(self, car):
        _v, _n, indices = car
        assert len(indices) % 3 == 0

    def test_no_index_points_past_the_vertices(self, car):
        vertices, _n, indices = car
        assert indices.max() < len(vertices)

    def test_the_car_is_about_the_size_of_a_car(self, car):
        vertices, _n, _i = car
        length = vertices[:, 2].max() - vertices[:, 2].min()
        width = vertices[:, 0].max() - vertices[:, 0].min()
        assert length == pytest.approx(CAR_LENGTH_M, abs=0.6)
        assert width == pytest.approx(CAR_WIDTH_M, abs=0.3)

    def test_the_car_sits_on_the_ground(self, car):
        # It is placed by adding a point on the track surface, so anything
        # below zero would sink into the tarmac.
        vertices, _n, _i = car
        assert vertices[:, 1].min() >= -0.01

    def test_the_car_is_centred_side_to_side(self, car):
        vertices, _n, _i = car
        assert abs(vertices[:, 0].mean()) < 0.05

    def test_the_normals_are_unit_length(self, car):
        _v, normals, _i = car
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)

    def test_it_is_light_enough_for_a_full_grid(self, car):
        # Twenty-two of these are drawn every frame.
        vertices, _n, indices = car
        assert len(vertices) < 400
        assert len(indices) < 800


class TestUpload:
    def test_the_buffer_interleaves_position_and_normal(self):
        data, indices = interleaved()
        vertices, _n, _i = build()
        assert len(data) == len(vertices) * 6 * 4  # six floats, four bytes
        assert len(indices) > 0
