"""Drawing the circuit in three dimensions.

The scene is deliberately small: a ground plane, a runoff apron, the racing
surface, and one instanced draw call for the whole field. Everything else on
screen stays two-dimensional and is drawn over the top, so the timing tower
and the panels are unaffected by any of this.
"""

from typing import Optional

import numpy as np
from arcade.gl import BufferDescription

from src.render.scene3d import car_mesh, shaders
from src.render.scene3d.mesh import (
    DEFAULT_ELEVATION_SCALE, DEFAULT_SPACING_M, DEFAULT_TRACK_WIDTH_M,
    resample_with_values, ribbon, surface_normals,
)
from src.render.scene3d.surface import TrackSurface

# A late afternoon sun, low and to one side, so the elevation casts the
# surface into light and shade rather than lighting it flat.
SUN_DIRECTION = (0.42, 0.78, 0.46)

ASPHALT = (0.232, 0.243, 0.276)
APRON = (0.118, 0.128, 0.150)
TRACK_EDGE = (0.88, 0.89, 0.92)
GROUND = (0.038, 0.042, 0.052)
FOG = (0.043, 0.048, 0.062)
FLAG_YELLOW = (0.84, 0.78, 0.24)

#: How much wider than the track the runoff apron is drawn.
APRON_WIDTH_FACTOR = 2.6

#: A car drawn to scale on a circuit a kilometre and a half across is three
#: pixels long, so from far away the cars are drawn larger than life. From
#: close up they are not: a car the size of a grandstand looks absurd.
MIN_CAR_SCALE = 1.0
MAX_CAR_SCALE = 6.5
CAR_SCALE_DISTANCE_M = 210.0
DEFAULT_CAR_SCALE = 4.0


def car_scale_for_distance(distance_m: float) -> float:
    """How much to oversize the cars, given how far away the camera is."""
    scale = float(distance_m) / CAR_SCALE_DISTANCE_M
    return float(np.clip(scale, MIN_CAR_SCALE, MAX_CAR_SCALE))

#: Per instance: where it is, which way it points, its colour, its size.
INSTANCE_FLOATS = 8


class Scene3D:
    """Holds the graphics resources for the circuit view."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.surface: Optional[TrackSurface] = None
        self.car_scale = DEFAULT_CAR_SCALE

        self._track_program = ctx.program(
            vertex_shader=shaders.TRACK_VERTEX,
            fragment_shader=shaders.TRACK_FRAGMENT)
        self._car_program = ctx.program(
            vertex_shader=shaders.CAR_VERTEX,
            fragment_shader=shaders.CAR_FRAGMENT)
        self._ground_program = ctx.program(
            vertex_shader=shaders.GROUND_VERTEX,
            fragment_shader=shaders.GROUND_FRAGMENT)

        self._track_geometry = None
        self._apron_geometry = None
        self._ground_geometry = None
        self._car_geometry = None
        self._instance_buffer = None
        self._instance_capacity = 0
        self._car_count = 0
        self._fog_distance = 4000.0

        self._build_car_geometry()

    # -- geometry ---------------------------------------------------------

    def _build_car_geometry(self) -> None:
        data, indices = car_mesh.interleaved()
        vertex_buffer = self.ctx.buffer(data=data)
        index_buffer = self.ctx.buffer(data=indices.tobytes())

        # Room for a full grid without reallocating every frame.
        self._instance_capacity = 32
        self._instance_buffer = self.ctx.buffer(
            reserve=self._instance_capacity * INSTANCE_FLOATS * 4)

        self._car_geometry = self.ctx.geometry(
            [
                BufferDescription(vertex_buffer, "3f 3f",
                                  ["in_position", "in_normal"]),
                BufferDescription(self._instance_buffer, "3f 1f 3f 1f",
                                  ["in_offset", "in_heading", "in_colour",
                                   "in_scale"],
                                  instanced=True),
            ],
            index_buffer=index_buffer,
            index_element_size=4,
        )

    def _upload_ribbon(self, strip):
        normals = surface_normals(strip.vertices, strip.indices)
        data = np.empty((len(strip.vertices), 9), dtype=np.float32)
        data[:, 0:3] = strip.vertices
        data[:, 3:6] = normals
        data[:, 6] = strip.along
        data[:, 7] = strip.side
        data[:, 8] = strip.kerb

        vertex_buffer = self.ctx.buffer(data=data.tobytes())
        index_buffer = self.ctx.buffer(data=strip.indices.tobytes())
        return self.ctx.geometry(
            [BufferDescription(vertex_buffer, "3f 3f 3f",
                               ["in_position", "in_normal", "in_surface"])],
            index_buffer=index_buffer,
            index_element_size=4,
        )

    def set_track(self, centre_x, centre_y, elevation,
                  width_m: float = DEFAULT_TRACK_WIDTH_M,
                  elevation_scale: float = DEFAULT_ELEVATION_SCALE,
                  spacing_m: float = DEFAULT_SPACING_M) -> None:
        """Build the circuit from a centreline and its elevation profile.

        The centreline is cleaned and evenly spaced first. A reference line
        taken from a telemetry lap repeats most of its points, and a
        repeated point has no direction, so the surface built from it turns
        inside out at every corner.
        """
        centre_x, centre_y, elevation = resample_with_values(
            centre_x, centre_y, elevation, spacing_m)

        self.surface = TrackSurface(centre_x, centre_y, elevation,
                                    elevation_scale)

        self._track_geometry = self._upload_ribbon(
            ribbon(centre_x, centre_y, elevation, width_m, elevation_scale))
        # The apron sits a little lower so it never fights the track for
        # the same pixels along the edges.
        self._apron_geometry = self._upload_ribbon(
            ribbon(centre_x, centre_y, np.asarray(elevation) - 0.12,
                   width_m * APRON_WIDTH_FACTOR, elevation_scale))

        self._build_ground()
        # Gentle: fog is here to give distance, not to swallow the circuit.
        self._fog_distance = max(self.surface.radius_world() * 9.0, 2000.0)

    def _build_ground(self) -> None:
        """A plane under the circuit, so it does not float in the void."""
        centre = self.surface.centre_world()
        # Far enough out that its edges never cross the frame. A visible
        # edge reads as a hard diagonal cutting across the circuit.
        reach = self.surface.radius_world() * 40.0
        height = -3.0

        corners = np.array([
            [centre[0] - reach, height, centre[2] - reach],
            [centre[0] + reach, height, centre[2] - reach],
            [centre[0] + reach, height, centre[2] + reach],
            [centre[0] - reach, height, centre[2] + reach],
        ], dtype=np.float32)
        indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

        self._ground_geometry = self.ctx.geometry(
            [BufferDescription(self.ctx.buffer(data=corners.tobytes()),
                               "3f", ["in_position"])],
            index_buffer=self.ctx.buffer(data=indices.tobytes()),
            index_element_size=4,
        )

    # -- per frame --------------------------------------------------------

    def set_cars(self, positions, headings, colours, scales=None) -> None:
        """Place the field for this frame.

        Args:
            positions: ``(n, 3)`` world positions.
            headings: ``(n,)`` headings in radians.
            colours: ``(n, 3)`` colours, each channel from zero to one.
            scales: ``(n,)`` sizes, or ``None`` for the default.
        """
        positions = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
        count = len(positions)
        self._car_count = count
        if not count:
            return

        if count > self._instance_capacity:
            self._instance_capacity = count * 2
            self._instance_buffer.orphan(
                size=self._instance_capacity * INSTANCE_FLOATS * 4)

        data = np.zeros((count, INSTANCE_FLOATS), dtype=np.float32)
        data[:, 0:3] = positions
        data[:, 3] = np.asarray(headings, dtype=np.float32).ravel()[:count]
        data[:, 4:7] = np.asarray(colours, dtype=np.float32).reshape(-1, 3)
        data[:, 7] = (self.car_scale if scales is None
                      else np.asarray(scales, dtype=np.float32).ravel()[:count])
        self._instance_buffer.write(data.tobytes())

    def draw(self, camera, width: float, height: float) -> None:
        """Render the scene. The caller owns the depth state around this."""
        if self._track_geometry is None:
            return

        aspect = width / max(height, 1e-6)
        view_projection = camera.view_projection_bytes(aspect)
        eye = tuple(float(v) for v in camera.position())

        self._ground_program["view_projection"] = view_projection
        self._ground_program["camera_position"] = eye
        self._ground_program["ground_colour"] = GROUND
        self._ground_program["fog_colour"] = FOG
        self._ground_program["fog_distance"] = self._fog_distance
        self._ground_geometry.render(self._ground_program)

        self._track_program["view_projection"] = view_projection
        self._track_program["camera_position"] = eye
        self._track_program["sun_direction"] = SUN_DIRECTION
        self._track_program["fog_colour"] = FOG
        self._track_program["fog_distance"] = self._fog_distance
        self._track_program["highlight"] = 0.0
        self._track_program["highlight_colour"] = FLAG_YELLOW

        # The apron first, with no edge lines or kerbs of its own.
        self._track_program["surface_colour"] = APRON
        self._track_program["edge_colour"] = APRON
        self._track_program["edge_width"] = 0.0
        self._track_program["kerb_enabled"] = 0.0
        self._track_program["start_line"] = -1.0
        self._apron_geometry.render(self._track_program)

        self._track_program["surface_colour"] = ASPHALT
        self._track_program["edge_colour"] = TRACK_EDGE
        self._track_program["edge_width"] = 0.075
        self._track_program["kerb_enabled"] = 1.0
        self._track_program["start_line"] = 0.0
        self._track_geometry.render(self._track_program)

        if self._car_count:
            self._car_program["view_projection"] = view_projection
            self._car_program["camera_position"] = eye
            self._car_program["sun_direction"] = SUN_DIRECTION
            self._car_program["fog_colour"] = FOG
            self._car_program["fog_distance"] = self._fog_distance
            self._car_geometry.render(self._car_program,
                                      instances=self._car_count)
