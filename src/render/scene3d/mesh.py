"""Building the circuit surface.

The track is a ribbon: two vertices per centreline point, offset either side
along the ground-plane perpendicular, raised to the elevation at that point.
Both edges of a segment sit at the same height, so the surface follows the
hill without banking every corner by accident.
"""

from dataclasses import dataclass

import numpy as np

#: The position feed measures the ground in tenths of a metre.
FEED_UNITS_PER_METRE = 10.0

#: A grand prix circuit is about fifteen metres wide. The ribbon is built a
#: little wider, because the white line and the kerbs beyond it are painted
#: onto the same strip.
RACING_SURFACE_WIDTH_M = 15.0
DEFAULT_TRACK_WIDTH_M = 19.2

#: Thirty metres of elevation across a kilometre of circuit is real, but it
#: reads as flat on screen. Broadcast graphics overstate it and so does this.
DEFAULT_ELEVATION_SCALE = 4.0


#: Curvature above this share of the circuit counts as a corner, and corners
#: are where the kerbs go.
CORNER_PERCENTILE = 78.0


@dataclass
class Ribbon:
    """A strip of surface, ready to hand to the graphics card.

    Attributes:
        vertices: ``(n, 3)`` world positions, Y-up, in metres.
        indices: Triangle indices into ``vertices``.
        along: Distance around the lap for each vertex, in metres.
        side: ``-1`` or ``1``, which edge of the track a vertex is on.
        kerb: ``1`` where the vertex is in a corner, ``0`` on a straight.
    """

    vertices: np.ndarray
    indices: np.ndarray
    along: np.ndarray
    side: np.ndarray
    kerb: np.ndarray


def corner_mask(x, y, percentile: float = CORNER_PERCENTILE) -> np.ndarray:
    """Which points of a centreline are in a corner.

    Curvature is how fast the heading turns per metre travelled. Taking the
    busiest share of the lap rather than a fixed threshold means the same
    rule works at Monaco and at Monza.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 5:
        return np.zeros(len(x))

    dx = np.roll(x, -1) - np.roll(x, 1)
    dy = np.roll(y, -1) - np.roll(y, 1)
    heading = np.unwrap(np.arctan2(dy, dx))
    step = np.hypot(dx, dy)
    step[step < 1e-9] = 1.0

    turn = np.abs(np.roll(heading, -1) - np.roll(heading, 1)) / step
    # Smooth, or single noisy samples become one-point kerbs.
    window = 5
    padded = np.concatenate([turn[-window:], turn, turn[:window]])
    smoothed = np.convolve(padded, np.ones(window) / window,
                           mode="same")[window:-window]

    return (smoothed >= np.percentile(smoothed, percentile)).astype(float)


def to_world(x, y, elevation,
             elevation_scale: float = 1.0) -> np.ndarray:
    """Convert feed coordinates to world space.

    The feed calls the ground plane X and Y and puts altitude in Z. World
    space is Y-up in metres, so the last two swap.
    """
    x = np.asarray(x, dtype=float) / FEED_UNITS_PER_METRE
    z = np.asarray(y, dtype=float) / FEED_UNITS_PER_METRE
    height = np.asarray(elevation, dtype=float) * float(elevation_scale)
    return np.column_stack([x, height, z])


def _ground_normals(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The perpendicular to the track at each point, in the ground plane."""
    # Central differences, wrapping, so the start line is not a corner.
    dx = np.roll(x, -1) - np.roll(x, 1)
    dy = np.roll(y, -1) - np.roll(y, 1)
    length = np.hypot(dx, dy)
    length[length < 1e-9] = 1.0
    # Rotate the tangent a quarter turn.
    return np.column_stack([-dy / length, dx / length])


def ribbon(centre_x, centre_y, elevation,
           width_m: float = DEFAULT_TRACK_WIDTH_M,
           elevation_scale: float = DEFAULT_ELEVATION_SCALE,
           kerb=None) -> Ribbon:
    """Build a closed strip of surface along a centreline.

    Args:
        centre_x: Centreline X, in feed units.
        centre_y: Centreline Y, in feed units.
        elevation: Height at each point, in metres.
        width_m: How wide the strip is, in metres.
        elevation_scale: How much to overstate the elevation.

    Returns:
        A :class:`Ribbon` whose last segment joins its first.
    """
    x = np.asarray(centre_x, dtype=float)
    y = np.asarray(centre_y, dtype=float)
    if len(x) < 3:
        raise ValueError("a circuit needs at least three points")

    height = np.asarray(elevation, dtype=float)
    if len(height) != len(x):
        height = np.zeros(len(x))

    normals = _ground_normals(x, y)
    half = (width_m * FEED_UNITS_PER_METRE) / 2.0
    left_x, left_y = x + normals[:, 0] * half, y + normals[:, 1] * half
    right_x, right_y = x - normals[:, 0] * half, y - normals[:, 1] * half

    left = to_world(left_x, left_y, height, elevation_scale)
    right = to_world(right_x, right_y, height, elevation_scale)

    # Interleaved, so a segment is four consecutive vertices.
    count = len(x)
    vertices = np.empty((count * 2, 3), dtype=float)
    vertices[0::2] = left
    vertices[1::2] = right

    step = np.hypot(np.diff(x, append=x[:1]), np.diff(y, append=y[:1]))
    distance = np.concatenate([[0.0], np.cumsum(step)[:-1]])
    distance = distance / FEED_UNITS_PER_METRE
    along = np.repeat(distance, 2)

    side = np.tile([1.0, -1.0], count)

    if kerb is None:
        kerb = corner_mask(x, y)
    kerb = np.repeat(np.asarray(kerb, dtype=float), 2)

    # Two triangles per segment, the last wrapping back to the first.
    first = np.arange(count)
    following = (first + 1) % count
    left_a, right_a = first * 2, first * 2 + 1
    left_b, right_b = following * 2, following * 2 + 1
    indices = np.column_stack([
        left_a, right_a, right_b,
        left_a, right_b, left_b,
    ]).reshape(-1).astype(np.uint32)

    # Whether that winding faces up or down depends on which way round the
    # circuit runs, and half the calendar runs anticlockwise. Face the sky.
    indices = _face_upwards(vertices, indices)

    return Ribbon(vertices=vertices, indices=indices, along=along, side=side,
                  kerb=kerb)


def _face_upwards(vertices: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Reverse the triangle winding if the surface came out upside down."""
    triangles = indices.reshape(-1, 3)
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    if np.cross(b - a, c - a)[:, 1].sum() >= 0:
        return indices
    return triangles[:, ::-1].reshape(-1).astype(np.uint32)


def surface_normals(vertices: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Per-vertex normals, averaged from the triangles that share them."""
    vertices = np.asarray(vertices, dtype=float)
    triangles = np.asarray(indices, dtype=np.int64).reshape(-1, 3)

    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    face = np.cross(b - a, c - a)

    normals = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)

    length = np.linalg.norm(normals, axis=1)
    # A degenerate triangle leaves a zero normal; point it up rather than
    # dividing by zero.
    flat = length < 1e-12
    normals[flat] = np.array([0.0, 1.0, 0.0])
    length[flat] = 1.0
    return normals / length[:, None]


#: How far apart to place centreline points when resampling, in metres.
DEFAULT_SPACING_M = 4.0


def resample_closed(x, y, spacing_m: float = DEFAULT_SPACING_M):
    """Clean a centreline and space its points evenly around the lap.

    The reference line that comes out of a telemetry lap is not fit to build
    geometry from: most of its points sit on top of each other, a few are
    hundreds of metres apart, and consecutive duplicates give no direction
    at all, so the perpendicular at those points is arbitrary and the
    surface folds itself inside out.

    Args:
        x: Centreline X, in feed units.
        y: Centreline Y, in feed units.
        spacing_m: How far apart the returned points should be.

    Returns:
        ``(x, y)`` in feed units, evenly spaced, still a closed loop.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if len(x) < 3:
        return x, y

    # Drop points that repeat the one before them.
    step = np.hypot(np.diff(x, append=x[:1]), np.diff(y, append=y[:1]))
    keep = step > 1e-6
    if keep.sum() < 3:
        return x, y
    x, y = x[keep], y[keep]

    # Walk the loop, including the closing leg back to the start.
    closed_x = np.append(x, x[0])
    closed_y = np.append(y, y[0])
    leg = np.hypot(np.diff(closed_x), np.diff(closed_y))
    distance = np.concatenate([[0.0], np.cumsum(leg)])
    total = distance[-1]
    if total <= 0:
        return x, y

    spacing = max(float(spacing_m), 0.1) * FEED_UNITS_PER_METRE
    count = max(int(round(total / spacing)), 8)
    wanted = np.linspace(0.0, total, count, endpoint=False)

    return (np.interp(wanted, distance, closed_x),
            np.interp(wanted, distance, closed_y))


def resample_with_values(x, y, values, spacing_m: float = DEFAULT_SPACING_M):
    """Resample a centreline and carry a per-point value along with it.

    Used for elevation, which is measured against the original points and
    has to follow them onto the evenly spaced ones.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    values = np.asarray(values, dtype=float).ravel()
    if len(values) != len(x):
        values = np.zeros(len(x))

    new_x, new_y = resample_closed(x, y, spacing_m)
    if len(new_x) == len(x) and np.array_equal(new_x, x):
        return new_x, new_y, values

    # Both describe the same loop, so a point a third of the way round one
    # is a third of the way round the other.
    original = _loop_fraction(x, y)
    resampled = _loop_fraction(new_x, new_y)
    wrapped_at = np.concatenate([original - 1.0, original, original + 1.0])
    wrapped_values = np.tile(values, 3)
    return new_x, new_y, np.interp(resampled, wrapped_at, wrapped_values)


def _loop_fraction(x, y) -> np.ndarray:
    """How far round the loop each point is, from zero to one."""
    step = np.hypot(np.diff(x, append=x[:1]), np.diff(y, append=y[:1]))
    distance = np.concatenate([[0.0], np.cumsum(step)[:-1]])
    total = distance[-1] + step[-1]
    return distance / total if total > 0 else distance
