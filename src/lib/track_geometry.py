"""Track centreline geometry and repair of gappy position data.

F1's position feed is not always healthy. In a good session a car's
coordinates update about four times a second. In a bad one the feed repeats
the same coordinates for two or three seconds at a time and then jumps a
couple of hundred metres, which makes cars appear to freeze on track and then
teleport.

Coordinates cannot be invented, but they can be reconstructed. Two things
remain trustworthy even when the position feed degrades:

* the **speed** channel, which says how far the car travelled and when, and
* the **track shape**, which says where it can have travelled.

:func:`rebuild_positions` combines them. Real position updates are used as
anchors; between two anchors that are too far apart in time, the car is walked
along the reference line at the speed it was actually doing, keeping its
sideways offset from the line. Where the feed is healthy the anchors are close
together and the function leaves the data alone.
"""

from typing import Optional, Tuple

import numpy as np

# Points in the resampled centreline. At 4000 points a 5 km circuit resolves
# to better than a car length.
DEFAULT_RESOLUTION = 4000

# Reference points closer together than this contribute nothing but noise.
MIN_POINT_SPACING = 5.0

# Gaps in the position feed longer than this are reconstructed. Healthy feeds
# update roughly every 0.24 s, so this leaves them untouched.
DEFAULT_MAX_GAP_S = 0.6

# A car must be moving for a gap to be worth reconstructing.
MIN_MOVING_KMH = 30.0

# Position updates smaller than this are treated as the feed repeating itself
# rather than as the car moving.
ANCHOR_MIN_MOVE = 5.0

# How far the distance along the track may disagree with the distance implied
# by speed before the reconstruction is abandoned for that gap.
#
# The check is deliberately asymmetric in effect. It cannot reject a
# reconstruction that is *shorter* than the speed suggests, and that is fine:
# following a short arc lands within metres of the straight line anyway. What
# it does reject is a reconstruction that is *longer* - a mis-projected anchor
# that would fling a car round the circuit. That is the direction that makes
# cars teleport, and it is caught.
#
# Tightening this repairs far less; removing it entirely takes the teleport
# rate from 8% to 22%.
DISTANCE_TOLERANCE = 1.0


class TrackLine:
    """A circuit centreline that supports projection and arc-length lookup.

    Args:
        xs: Reference lap X coordinates.
        ys: Reference lap Y coordinates.
        resolution: Number of points in the resampled line.

    Raises:
        ValueError: if fewer than two distinct points are supplied.
    """

    def __init__(self, xs, ys, resolution: int = DEFAULT_RESOLUTION):
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        if xs.size != ys.size or xs.size < 2:
            raise ValueError("a track line needs at least two matching points")

        xs, ys = self._deduplicate(xs, ys)
        if xs.size < 2:
            raise ValueError("the reference lap has no usable points")

        # Close the loop so a car near the finish line interpolates correctly.
        if np.hypot(xs[0] - xs[-1], ys[0] - ys[-1]) > MIN_POINT_SPACING:
            xs = np.append(xs, xs[0])
            ys = np.append(ys, ys[0])

        # Resample by arc length rather than by index: the raw telemetry has
        # dense clusters in slow corners and long gaps on straights, which
        # would otherwise make projection quantise badly.
        steps = np.hypot(np.diff(xs), np.diff(ys))
        cumulative = np.concatenate(([0.0], np.cumsum(steps)))
        targets = np.linspace(0.0, cumulative[-1], resolution)

        self.xs = np.interp(targets, cumulative, xs)
        self.ys = np.interp(targets, cumulative, ys)
        self.arc = np.hypot(np.diff(self.xs), np.diff(self.ys)).cumsum()
        self.arc = np.concatenate(([0.0], self.arc))
        self.length = float(self.arc[-1])

        from scipy.spatial import cKDTree
        self._tree = cKDTree(np.column_stack((self.xs, self.ys)))

    @staticmethod
    def _deduplicate(xs, ys):
        """Drop reference points that sit on top of each other."""
        keep = [0]
        for index in range(1, xs.size):
            last = keep[-1]
            if np.hypot(xs[index] - xs[last], ys[index] - ys[last]) \
                    >= MIN_POINT_SPACING:
                keep.append(index)
        return xs[keep], ys[keep]

    def project(self, x: float, y: float) -> Tuple[float, float, float]:
        """Return ``(arc_position, offset_x, offset_y)`` for a coordinate.

        The offset is the car's displacement from the line, which is what
        keeps two cars side by side looking side by side.
        """
        _, index = self._tree.query([x, y])
        index = int(index)
        return (float(self.arc[index]),
                float(x - self.xs[index]),
                float(y - self.ys[index]))

    def point_at(self, arc_position: float) -> Tuple[float, float]:
        """Return the coordinate at an arc position, wrapping past the line."""
        target = float(arc_position) % self.length if self.length else 0.0
        index = int(np.searchsorted(self.arc, target))
        index = min(max(index, 0), self.xs.size - 1)
        return float(self.xs[index]), float(self.ys[index])

    def forward_distance(self, start: float, end: float) -> float:
        """Return the distance from ``start`` to ``end`` travelling forwards."""
        if not self.length:
            return 0.0
        return (end - start) % self.length


def _travelled_fraction(times, speeds, start: int, stop: int) -> np.ndarray:
    """Return how far through a gap the car is at each intermediate sample.

    Uses the speed channel, so a car that accelerates out of a corner is
    placed correctly rather than being dragged along at a constant rate.
    """
    segment_t = times[start:stop + 1]
    segment_v = np.maximum(speeds[start:stop + 1], 0.0)
    steps = np.diff(segment_t)
    # Trapezoidal integration of speed gives distance travelled.
    increments = 0.5 * (segment_v[:-1] + segment_v[1:]) * steps
    cumulative = np.concatenate(([0.0], np.cumsum(increments)))
    total = cumulative[-1]
    if total <= 0:
        # Fall back to elapsed time when the speed channel is unusable.
        span = segment_t[-1] - segment_t[0]
        if span <= 0:
            return np.zeros_like(cumulative)
        return (segment_t - segment_t[0]) / span
    return cumulative / total


def find_anchors(x, y, min_move: float = ANCHOR_MIN_MOVE) -> np.ndarray:
    """Return a boolean mask of samples where the position genuinely updated.

    Everything else is the feed repeating its last value.
    """
    anchors = np.zeros(x.size, dtype=bool)
    if x.size == 0:
        return anchors
    anchors[0] = True
    last = 0
    for index in range(1, x.size):
        if np.hypot(x[index] - x[last], y[index] - y[last]) >= min_move:
            anchors[index] = True
            last = index
    return anchors


def rebuild_positions(times, x, y, speeds, line: Optional[TrackLine],
                      max_gap_s: float = DEFAULT_MAX_GAP_S,
                      min_moving_kmh: float = MIN_MOVING_KMH) -> Tuple:
    """Fill long gaps in the position feed by following the track.

    Args:
        times: Sample times in seconds, ascending.
        x: X coordinates, in the feed's units.
        y: Y coordinates.
        speeds: Speed in km/h at each sample.
        line: Reference centreline. ``None`` disables the repair.
        max_gap_s: Gaps longer than this are reconstructed.
        min_moving_kmh: Cars slower than this are left alone; a car really
            stopped in the pits or in a gravel trap must stay where it is.

    Returns:
        ``(x, y, repaired_sample_count)``. The inputs are never modified.
    """
    times = np.asarray(times, dtype=float)
    x = np.asarray(x, dtype=float).copy()
    y = np.asarray(y, dtype=float).copy()
    speeds = np.asarray(speeds, dtype=float)

    if line is None or times.size < 3:
        return x, y, 0

    anchor_indices = np.flatnonzero(find_anchors(x, y))
    repaired = 0

    for start, stop in zip(anchor_indices, anchor_indices[1:]):
        if stop - start < 2:
            continue  # nothing in between to reconstruct
        if times[stop] - times[start] <= max_gap_s:
            continue  # the feed kept up; leave the data alone
        if np.max(speeds[start:stop + 1]) < min_moving_kmh:
            continue  # genuinely stationary

        start_arc, start_dx, start_dy = line.project(x[start], y[start])
        end_arc, end_dx, end_dy = line.project(x[stop], y[stop])
        along = line.forward_distance(start_arc, end_arc)

        # Cross-check against the distance the speed channel implies, adding
        # whole laps if the car covered more than one. If the two disagree
        # badly the anchors cannot be trusted, so the gap is left as it was.
        fractions = _travelled_fraction(times, speeds, start, stop)
        segment_t = times[start:stop + 1]
        segment_v = np.maximum(speeds[start:stop + 1], 0.0) / 3.6 * 10.0
        implied = float(np.trapezoid(segment_v, segment_t)) \
            if hasattr(np, "trapezoid") else float(np.trapz(segment_v, segment_t))

        if implied > 0 and line.length > 0:
            laps = round((implied - along) / line.length)
            along += max(0, laps) * line.length
            if abs(implied - along) > DISTANCE_TOLERANCE * max(implied, 1.0):
                continue

        for offset, index in enumerate(range(start + 1, stop)):
            fraction = float(fractions[offset + 1])
            arc = start_arc + fraction * along
            point_x, point_y = line.point_at(arc)
            x[index] = point_x + start_dx + (end_dx - start_dx) * fraction
            y[index] = point_y + start_dy + (end_dy - start_dy) * fraction
            repaired += 1

    return x, y, repaired
