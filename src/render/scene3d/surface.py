"""Placing things on the circuit surface.

A car has an X and a Y from the feed but no height and no heading. Both come
from the track: the nearest point on the centreline gives the elevation to
sit at and the direction to point in. Taking the heading from the track
rather than from the car's own movement keeps it steady when the position
feed jitters, which it does.
"""

import numpy as np

from src.render.scene3d.mesh import FEED_UNITS_PER_METRE, to_world


class TrackSurface:
    """The centreline, its elevation, and which way it faces."""

    def __init__(self, centre_x, centre_y, elevation,
                 elevation_scale: float = 1.0):
        self.x = np.asarray(centre_x, dtype=float)
        self.y = np.asarray(centre_y, dtype=float)
        if len(self.x) < 2:
            raise ValueError("a circuit needs at least two points")

        elevation = np.asarray(elevation, dtype=float)
        if len(elevation) != len(self.x):
            elevation = np.zeros(len(self.x))
        self.elevation = elevation
        self.elevation_scale = float(elevation_scale)

        # Heading at each point, wrapping so the start line is not a corner.
        dx = np.roll(self.x, -1) - np.roll(self.x, 1)
        dy = np.roll(self.y, -1) - np.roll(self.y, 1)
        # World Z is the feed's Y, and the car model points down -Z, so a
        # heading of zero faces -Z and turns towards +X.
        self.heading = np.arctan2(dx, -dy) + np.pi / 2.0

        self._points = np.column_stack([self.x, self.y])
        self._tree = None
        try:
            from scipy.spatial import cKDTree

            self._tree = cKDTree(self._points)
        except Exception:
            self._tree = None

    def nearest(self, x, y) -> np.ndarray:
        """Index of the closest centreline point to each position."""
        query = np.column_stack([np.asarray(x, dtype=float).ravel(),
                                 np.asarray(y, dtype=float).ravel()])
        if not len(query):
            return np.zeros(0, dtype=int)
        if self._tree is not None:
            return self._tree.query(query)[1].astype(int)

        # Without scipy, fall back to the slow way rather than failing.
        deltas = query[:, None, :] - self._points[None, :, :]
        return np.argmin(np.einsum("ijk,ijk->ij", deltas, deltas), axis=1)

    def place(self, x, y):
        """Where cars sit and which way they face.

        Args:
            x: Feed X coordinates.
            y: Feed Y coordinates.

        Returns:
            ``(world_positions, headings)``, world positions in metres, Y-up.
        """
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        if not len(x):
            return np.zeros((0, 3)), np.zeros(0)

        index = self.nearest(x, y)
        world = to_world(x, y, self.elevation[index], self.elevation_scale)
        return world, self.heading[index]

    def centre_world(self) -> np.ndarray:
        """The middle of the circuit, for the camera to orbit.

        The middle of what the circuit covers, not the average of its
        points: a long straight is sampled as densely as a hairpin, so an
        average pulls the centre towards whichever part has more corners.
        """
        return np.array([
            (self.x.min() + self.x.max()) / 2.0 / FEED_UNITS_PER_METRE,
            float(np.mean(self.elevation) * self.elevation_scale),
            (self.y.min() + self.y.max()) / 2.0 / FEED_UNITS_PER_METRE,
        ])

    def radius_world(self) -> float:
        """Roughly how far the circuit reaches from its centre, in metres."""
        centre = self.centre_world()
        dx = self.x / FEED_UNITS_PER_METRE - centre[0]
        dz = self.y / FEED_UNITS_PER_METRE - centre[2]
        return float(np.hypot(dx, dz).max())
