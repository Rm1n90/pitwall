"""Tests that the 3D scene actually renders.

These draw into an offscreen buffer and read the pixels back, which is the
only way to tell a shader that works from one that compiles.
"""

import numpy as np
import pytest

arcade = pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.render.scene3d.camera import Camera3D  # noqa: E402
from src.render.scene3d.renderer import Scene3D  # noqa: E402

SIZE = (240, 180)


@pytest.fixture(scope="module")
def window():
    win = arcade.Window(SIZE[0], SIZE[1], "scene test", visible=False)
    yield win
    win.close()


@pytest.fixture
def target(window):
    ctx = window.ctx
    buffer = ctx.framebuffer(
        color_attachments=[ctx.texture(SIZE, components=4)],
        depth_attachment=ctx.depth_texture(SIZE))
    buffer.use()
    buffer.clear(color=(0, 0, 0, 255))
    ctx.enable(ctx.DEPTH_TEST)
    return buffer


def oval(points=120, radius=1200.0):
    angle = np.linspace(0.0, 2 * np.pi, points, endpoint=False)
    return radius * np.cos(angle), radius * 0.6 * np.sin(angle)


def pixels(target):
    raw = np.frombuffer(target.read(components=4), dtype=np.uint8)
    return raw.reshape(SIZE[1], SIZE[0], 4)[:, :, :3]


def lit_fraction(image, threshold=12):
    return float((image.sum(axis=2) > threshold).mean())


@pytest.fixture
def scene(window):
    scene = Scene3D(window.ctx)
    x, y = oval()
    scene.set_track(x, y, np.linspace(0.0, 30.0, len(x)))
    return scene


@pytest.fixture
def camera(scene):
    centre = scene.surface.centre_world()
    return Camera3D(target=centre, distance=scene.surface.radius_world() * 2.2,
                    yaw=0.6, pitch=np.deg2rad(30.0))


class TestTrack:
    def test_the_circuit_is_drawn(self, scene, camera, target):
        scene.draw(camera, *SIZE)
        assert lit_fraction(pixels(target)) > 0.2

    def test_an_empty_scene_draws_nothing(self, window, camera, target):
        Scene3D(window.ctx).draw(camera, *SIZE)
        assert lit_fraction(pixels(target)) == 0.0

    def test_looking_away_leaves_the_circuit_off_screen(self, scene, target):
        # A camera under the ground pointing at the sky sees no track.
        away = Camera3D(target=(0.0, 90000.0, 0.0), distance=100.0,
                        pitch=np.deg2rad(85.0))
        scene.draw(away, *SIZE)
        assert lit_fraction(pixels(target)) < 0.05

    def test_the_view_changes_when_the_camera_moves(self, scene, camera,
                                                    target):
        scene.draw(camera, *SIZE)
        first = pixels(target).copy()

        target.clear(color=(0, 0, 0, 255))
        camera.orbit(1.2, 0.0)
        scene.draw(camera, *SIZE)

        assert not np.array_equal(first, pixels(target))

    def test_elevation_changes_what_is_drawn(self, window, camera, target):
        ctx = window.ctx
        x, y = oval()

        flat = Scene3D(ctx)
        flat.set_track(x, y, np.zeros(len(x)))
        flat.draw(camera, *SIZE)
        flat_image = pixels(target).copy()

        target.clear(color=(0, 0, 0, 255))
        hilly = Scene3D(ctx)
        hilly.set_track(x, y, np.linspace(0.0, 60.0, len(x)))
        hilly.draw(camera, *SIZE)

        assert not np.array_equal(flat_image, pixels(target))


class TestCars:
    def test_cars_are_drawn_on_the_track(self, scene, camera, target):
        scene.draw(camera, *SIZE)
        without = pixels(target).copy()

        target.clear(color=(0, 0, 0, 255))
        x, y = oval()
        positions, headings = scene.surface.place(x[:20], y[:20])
        scene.set_cars(positions, headings,
                       np.tile([1.0, 0.1, 0.1], (20, 1)))
        scene.draw(camera, *SIZE)
        with_cars = pixels(target)

        assert not np.array_equal(without, with_cars)
        # Red cars on grey asphalt: the red channel has to gain.
        assert with_cars[:, :, 0].sum() > without[:, :, 0].sum()

    def test_a_field_larger_than_the_buffer_still_draws(self, scene, camera,
                                                       target):
        # The instance buffer starts with room for a normal grid.
        x, y = oval(200)
        positions, headings = scene.surface.place(x[:60], y[:60])
        scene.set_cars(positions, headings,
                       np.tile([0.2, 0.9, 0.4], (60, 1)))
        scene.draw(camera, *SIZE)
        assert lit_fraction(pixels(target)) > 0.2

    def test_no_cars_is_not_an_error(self, scene, camera, target):
        scene.set_cars(np.zeros((0, 3)), np.zeros(0), np.zeros((0, 3)))
        scene.draw(camera, *SIZE)
        assert lit_fraction(pixels(target)) > 0.2

    def test_car_colours_reach_the_screen(self, scene, camera, target):
        x, y = oval()
        positions, headings = scene.surface.place(x[:20], y[:20])

        scene.set_cars(positions, headings, np.tile([0.05, 0.05, 1.0], (20, 1)))
        scene.draw(camera, *SIZE)
        blue = pixels(target).copy()

        target.clear(color=(0, 0, 0, 255))
        scene.set_cars(positions, headings, np.tile([1.0, 0.05, 0.05], (20, 1)))
        scene.draw(camera, *SIZE)
        red = pixels(target)

        assert red[:, :, 0].sum() > blue[:, :, 0].sum()
        assert blue[:, :, 2].sum() > red[:, :, 2].sum()
