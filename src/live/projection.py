"""Projection of car coordinates onto the track centre line.

Live feeds give raw ``X``/``Y`` coordinates but the replay needs a lap
fraction (``rel_dist``) and a cumulative race distance (``dist``) for every
car. Both are derived by projecting the car onto a dense polyline built from
the reference lap.
"""

from typing import Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree

# Resolution of the polyline the cars are projected onto. 4000 points keeps
# the error well under a car length on every circuit on the calendar.
POLYLINE_POINTS = 4000


class TrackProjector:
    """Maps ``(x, y)`` coordinates onto a position along the lap.

    Args:
        xs: Reference lap X coordinates.
        ys: Reference lap Y coordinates.
        length_m: Real lap length in metres. When omitted, the polyline length
            is used, which is in feed units rather than metres.
    """

    def __init__(self, xs, ys, length_m: Optional[float] = None):
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        if xs.size < 2 or xs.size != ys.size:
            raise ValueError("a track reference needs at least two points")

        source = np.linspace(0.0, 1.0, xs.size)
        target = np.linspace(0.0, 1.0, POLYLINE_POINTS)
        self.xs = np.interp(target, source, xs)
        self.ys = np.interp(target, source, ys)

        steps = np.sqrt(np.diff(self.xs) ** 2 + np.diff(self.ys) ** 2)
        self.cumulative = np.concatenate(([0.0], np.cumsum(steps)))
        self.polyline_length = float(self.cumulative[-1]) or 1.0
        self.length_m = float(length_m) if length_m else self.polyline_length

        self._tree = cKDTree(np.column_stack((self.xs, self.ys)))

    def relative_distance(self, x: float, y: float) -> float:
        """Return the lap fraction (0.0 to 1.0) closest to ``(x, y)``."""
        _, index = self._tree.query([x, y])
        return float(self.cumulative[int(index)] / self.polyline_length)

    def relative_distances(self, points) -> np.ndarray:
        """Vectorised :meth:`relative_distance` for many points at once."""
        points = np.asarray(points, dtype=float)
        if points.size == 0:
            return np.empty(0)
        _, indices = self._tree.query(points)
        return self.cumulative[indices] / self.polyline_length

    def point_at(self, relative_distance: float) -> Tuple[float, float]:
        """Return the track coordinate at a given lap fraction."""
        fraction = float(relative_distance) % 1.0
        target = fraction * self.polyline_length
        index = int(np.searchsorted(self.cumulative, target))
        index = min(max(index, 0), len(self.xs) - 1)
        return float(self.xs[index]), float(self.ys[index])

    def advance(self, relative_distance: float, metres: float) -> float:
        """Move ``metres`` further along the lap from a lap fraction."""
        return (float(relative_distance) + metres / max(1.0, self.length_m)) % 1.0
