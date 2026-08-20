"""Drawing the circuit.

The track used to be two thin grey lines. This draws it as a surface: asphalt
between the edges, kerbs on the corners, numbered corners, the pit lane, and a
start/finish line. Everything that does not change between frames is baked
into GPU buffers when the window is sized, so the per-frame cost is a handful
of draw calls rather than thousands of line segments.
"""

from typing import List, Optional, Sequence, Tuple

import arcade
from arcade import shape_list

# Asphalt, and the painted edge either side of it.
SURFACE_COLOR = (58, 61, 69)
SURFACE_EDGE_COLOR = (132, 138, 152)
RUNOFF_COLOR = (28, 30, 35)

# Kerbs alternate along the outside of a corner.
KERB_RED = (198, 58, 58)
KERB_WHITE = (226, 226, 230)
# Points per stripe. Short stripes vanish at normal window sizes.
KERB_STRIPE_POINTS = 7

# Everything else on the surface.
PIT_LANE_COLOR = (58, 62, 72)
PIT_LANE_EDGE_COLOR = (120, 126, 140)
PIT_LABEL_COLOR = (150, 158, 175)
CORNER_LABEL_COLOR = (128, 134, 148)
DRS_COLOR = (0, 168, 92)
START_LINE_COLOR = (236, 238, 242)

# How wide the runoff apron around the circuit is, relative to track width.
RUNOFF_SCALE = 1.9

# Which share of the lap counts as corner. Curvature varies hugely between
# circuits, so this is a percentile rather than an absolute threshold: the
# bendiest fifth of the lap gets kerbs, whether that is Monaco or Monza.
CORNER_PERCENTILE = 82


def _resample(xs, ys, count: int):
    """Return ``count`` points spaced evenly along a path."""
    import numpy as np

    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    steps = np.hypot(np.diff(xs), np.diff(ys))
    cumulative = np.concatenate(([0.0], np.cumsum(steps)))
    if cumulative[-1] <= 0:
        return xs, ys
    targets = np.linspace(0.0, cumulative[-1], count)
    return np.interp(targets, cumulative, xs), np.interp(targets, cumulative, ys)


def _offset_edges(xs, ys, width: float):
    """Return the outer and inner edges either side of a closed path.

    Which side the surface normal points to depends on whether the circuit
    runs clockwise or anticlockwise, so the winding is measured and the two
    edges swapped when needed. Without that, "outer" means the inside of the
    track on half the calendar.
    """
    import numpy as np

    dx = np.gradient(xs)
    dy = np.gradient(ys)
    norm = np.hypot(dx, dy)
    norm[norm == 0] = 1.0
    nx, ny = -dy / norm, dx / norm

    # Shoelace formula: a positive area means an anticlockwise loop, whose
    # left-hand normal points inwards.
    area = float(np.sum(xs[:-1] * ys[1:] - xs[1:] * ys[:-1])
                 + xs[-1] * ys[0] - xs[0] * ys[-1])
    if area > 0:
        nx, ny = -nx, -ny

    half = width / 2.0
    return (xs + nx * half, ys + ny * half), (xs - nx * half, ys - ny * half)


def _curvature(xs, ys):
    """Return how sharply the path bends at each point."""
    import numpy as np

    dx, dy = np.gradient(xs), np.gradient(ys)
    ddx, ddy = np.gradient(dx), np.gradient(dy)
    speed = np.hypot(dx, dy)
    speed[speed == 0] = 1.0
    return np.abs(dx * ddy - dy * ddx) / speed ** 3


class TrackRenderer:
    """Builds and draws the circuit for one session.

    Args:
        centre_x: Reference line X coordinates, in world units.
        centre_y: Reference line Y coordinates.
        track_width: Width of the racing surface in world units.
        corners: Optional ``(x, y, label)`` tuples for corner numbers.
        pit_lane: Optional ``(x, y)`` path for the pit lane.
        drs_zones: Optional list of ``(start_index, end_index)`` along the
            reference line.
    """

    def __init__(self, centre_x, centre_y, track_width: float,
                 corners: Optional[Sequence] = None,
                 pit_lane: Optional[Sequence] = None,
                 drs_zones: Optional[Sequence] = None,
                 marshal_sectors: Optional[Sequence] = None,
                 resolution: int = 900):
        import numpy as np

        self.centre_x, self.centre_y = _resample(centre_x, centre_y, resolution)
        self.track_width = float(track_width)
        self.corners = list(corners or [])
        self.pit_lane = list(pit_lane or [])
        self.drs_zones = list(drs_zones or [])

        (self.outer_x, self.outer_y), (self.inner_x, self.inner_y) = \
            _offset_edges(self.centre_x, self.centre_y, self.track_width)
        (self.runoff_out_x, self.runoff_out_y), (self.runoff_in_x, self.runoff_in_y) = \
            _offset_edges(self.centre_x, self.centre_y,
                          self.track_width * RUNOFF_SCALE)

        curvature = _curvature(self.centre_x, self.centre_y)
        threshold = float(np.percentile(curvature, CORNER_PERCENTILE))
        self.is_corner = curvature > max(threshold, 1e-9)

        # Where each marshalling sector begins along the reference line, so a
        # flag can light up the stretch it actually applies to.
        self._sector_starts = self._index_marshal_sectors(marshal_sectors)

        self._shapes = None
        self._corner_labels: List[arcade.Text] = []
        self._pit_label: Optional[arcade.Text] = None

    def _index_marshal_sectors(self, sectors) -> dict:
        """Map each marshalling sector number to an index on the centre line."""
        import numpy as np

        if not sectors:
            return {}
        points = np.column_stack((self.centre_x, self.centre_y))
        indexed = {}
        for number, x, y in sectors:
            distances = np.hypot(points[:, 0] - x, points[:, 1] - y)
            indexed[int(number)] = int(np.argmin(distances))
        return indexed

    def sector_span(self, number: int):
        """Return the ``(start, stop)`` line indices a sector covers.

        A sector runs from its own marker to the next one round the lap.
        Returns ``None`` when the circuit's sectors are unknown.
        """
        if not self._sector_starts:
            return None
        start = self._sector_starts.get(int(number))
        if start is None:
            return None
        later = sorted(v for v in self._sector_starts.values() if v > start)
        stop = later[0] if later else len(self.centre_x) - 1
        return start, stop

    # -- building ---------------------------------------------------------

    def rebuild(self, to_screen) -> None:
        """Rebuild the baked geometry for a new window size or rotation.

        Args:
            to_screen: Callable mapping world ``(x, y)`` to screen ``(x, y)``.
        """
        shapes = shape_list.ShapeElementList()

        shapes.append(self._band(to_screen,
                                 self.runoff_in_x, self.runoff_in_y,
                                 self.runoff_out_x, self.runoff_out_y,
                                 RUNOFF_COLOR))

        # The pit lane runs alongside the main straight, so it is drawn first
        # and the racing surface covers it wherever the two overlap.
        if self.pit_lane:
            for element in self._pit_lane_shapes(to_screen):
                shapes.append(element)

        shapes.append(self._band(to_screen,
                                 self.inner_x, self.inner_y,
                                 self.outer_x, self.outer_y,
                                 SURFACE_COLOR))

        for element in self._kerbs(to_screen):
            shapes.append(element)

        for xs, ys in ((self.inner_x, self.inner_y), (self.outer_x, self.outer_y)):
            points = [to_screen(x, y) for x, y in zip(xs, ys)]
            shapes.append(shape_list.create_line_strip(
                points, SURFACE_EDGE_COLOR, 1.4))

        self._shapes = shapes
        self._build_labels(to_screen)

    def _band(self, to_screen, inner_x, inner_y, outer_x, outer_y, color):
        """Bake a filled ribbon between two edges."""
        points = []
        colors = []
        for ix, iy, ox, oy in zip(inner_x, inner_y, outer_x, outer_y):
            points.append(to_screen(ix, iy))
            points.append(to_screen(ox, oy))
            colors.append(color)
            colors.append(color)
        # Close the loop back onto the first pair.
        points.append(to_screen(inner_x[0], inner_y[0]))
        points.append(to_screen(outer_x[0], outer_y[0]))
        colors.extend([color, color])
        return shape_list.create_triangles_strip_filled_with_colors(
            points, colors)

    def _kerbs(self, to_screen):
        """Bake alternating red and white stripes along corner edges."""
        elements = []
        for xs, ys in ((self.inner_x, self.inner_y), (self.outer_x, self.outer_y)):
            run_start = None
            for index in range(len(xs)):
                if self.is_corner[index] and run_start is None:
                    run_start = index
                elif not self.is_corner[index] and run_start is not None:
                    elements.extend(
                        self._stripes(to_screen, xs, ys, run_start, index))
                    run_start = None
            if run_start is not None:
                elements.extend(
                    self._stripes(to_screen, xs, ys, run_start, len(xs)))
        return elements

    def _stripes(self, to_screen, xs, ys, start: int, stop: int):
        """Bake one run of kerb stripes between two indices."""
        elements = []
        stripe = KERB_STRIPE_POINTS
        for begin in range(start, stop - 1, stripe):
            end = min(begin + stripe, stop)
            if end - begin < 2:
                continue
            color = KERB_RED if ((begin - start) // stripe) % 2 == 0 \
                else KERB_WHITE
            points = [to_screen(xs[i], ys[i]) for i in range(begin, end)]
            elements.append(shape_list.create_line_strip(points, color, 3.0))
        return elements

    def _pit_lane_shapes(self, to_screen):
        """Bake the pit lane surface and its edges."""
        import numpy as np

        xs = np.array([p[0] for p in self.pit_lane], dtype=float)
        ys = np.array([p[1] for p in self.pit_lane], dtype=float)
        (ox, oy), (ix, iy) = _offset_edges(xs, ys, self.track_width * 0.55)

        points, colors = [], []
        for a, b, c, d in zip(ix, iy, ox, oy):
            points.append(to_screen(a, b))
            points.append(to_screen(c, d))
            colors.extend([PIT_LANE_COLOR, PIT_LANE_COLOR])
        elements = [shape_list.create_triangles_strip_filled_with_colors(
            points, colors)]
        for ex, ey in ((ix, iy), (ox, oy)):
            elements.append(shape_list.create_line_strip(
                [to_screen(x, y) for x, y in zip(ex, ey)],
                PIT_LANE_EDGE_COLOR, 1.2))
        return elements

    def _build_labels(self, to_screen) -> None:
        """Position the corner numbers and the pit lane label."""
        self._corner_labels = []
        for x, y, label in self.corners:
            screen_x, screen_y = to_screen(x, y)
            self._corner_labels.append(arcade.Text(
                str(label), screen_x, screen_y, CORNER_LABEL_COLOR, 9,
                anchor_x="center", anchor_y="center", bold=True))

        self._pit_label = None
        if self.pit_lane:
            middle = self.pit_lane[len(self.pit_lane) // 2]
            screen_x, screen_y = to_screen(*middle)
            self._pit_label = arcade.Text(
                "PIT LANE", screen_x, screen_y, PIT_LABEL_COLOR, 8,
                anchor_x="center", anchor_y="center", bold=True)

    # -- drawing ----------------------------------------------------------

    def draw(self, to_screen, show_drs: bool = True,
             status_color: Optional[Tuple[int, int, int]] = None,
             flagged_sectors: Optional[Sequence] = None) -> None:
        """Draw the circuit. ``rebuild`` must have been called first.

        Args:
            to_screen: World to screen mapping.
            show_drs: Whether to mark the DRS zones.
            status_color: Tint for the track edges when not under green flags.
            flagged_sectors: ``(sector_number, colour)`` pairs to light up.
        """
        if self._shapes is None:
            return
        self._shapes.draw()

        if flagged_sectors:
            self._draw_flagged(to_screen, flagged_sectors)

        if show_drs:
            self._draw_drs(to_screen)

        if status_color is not None:
            self._draw_status_edge(to_screen, status_color)

        for label in self._corner_labels:
            label.draw()
        if self._pit_label is not None:
            self._pit_label.draw()

    def _draw_drs(self, to_screen) -> None:
        """Mark the DRS zones as a line just inside the surface."""
        for start, stop in self.drs_zones:
            if stop <= start:
                continue
            points = [to_screen(self.centre_x[i], self.centre_y[i])
                      for i in range(start, min(stop, len(self.centre_x)))]
            if len(points) > 1:
                arcade.draw_line_strip(points, DRS_COLOR, 2.0)

    def _draw_flagged(self, to_screen, flagged) -> None:
        """Light up the stretches of track under a flag."""
        for number, color in flagged:
            span = self.sector_span(number)
            if span is None:
                continue
            start, stop = span
            for xs, ys in ((self.inner_x, self.inner_y),
                           (self.outer_x, self.outer_y)):
                points = [to_screen(xs[i], ys[i])
                          for i in range(start, min(stop + 1, len(xs)))]
                if len(points) > 1:
                    arcade.draw_line_strip(points, color, 5.0)

    def _draw_status_edge(self, to_screen, color) -> None:
        """Tint the track edges when the session is not under green flags."""
        for xs, ys in ((self.inner_x, self.inner_y),
                       (self.outer_x, self.outer_y)):
            points = [to_screen(x, y) for x, y in zip(xs, ys)]
            arcade.draw_line_strip(points, color, 2.4)


def corner_labels_from_circuit_info(circuit_info) -> List[Tuple]:
    """Return ``(x, y, label)`` corner markers from FastF1 circuit info.

    Returns an empty list when the information is unavailable, so callers do
    not have to special-case a session without it.
    """
    corners = getattr(circuit_info, "corners", None)
    if corners is None or len(corners) == 0:
        return []
    labels = []
    for _, corner in corners.iterrows():
        try:
            number = int(corner["Number"])
        except (TypeError, ValueError):
            continue
        letter = str(corner.get("Letter") or "").strip()
        labels.append((float(corner["X"]), float(corner["Y"]),
                       f"{number}{letter}"))
    return labels
