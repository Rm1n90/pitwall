"""Small drawing helpers.

Arcade has no rounded rectangle, so a pill is composed from a rectangle and
two end circles. The playback controls are round, and a square-cornered slab
sitting among them looks like something that was never finished.
"""

import arcade

#: A recessed tray: darker than the buttons that sit on it, so they stand out.
TRAY_FILL = (26, 27, 32, 235)
#: A hairline edge, so the tray reads as deliberate against a black page.
TRAY_BORDER = (255, 255, 255, 28)
TRAY_BORDER_WIDTH = 1.5


def pill_geometry(center_x: float, center_y: float,
                  width: float, height: float):
    """Return the rectangle and two end circles that make up a pill.

    Args:
        center_x: Centre of the pill.
        center_y: Centre of the pill.
        width: Overall width, end to end.
        height: Overall height, which is also the diameter of the ends.

    Returns:
        ``((rect_cx, rect_cy, rect_w, rect_h), (left_x, y, radius),
        (right_x, y, radius))``. A pill narrower than it is tall collapses to
        a single circle, which is what a circle is.
    """
    radius = height / 2.0
    body_width = max(0.0, width - height)
    return (
        (center_x, center_y, body_width, height),
        (center_x - body_width / 2.0, center_y, radius),
        (center_x + body_width / 2.0, center_y, radius),
    )


def _fill_pill(center_x: float, center_y: float, width: float, height: float,
               color) -> None:
    """Draw a pill in one flat tone.

    The caps are half circles rather than whole ones. A whole circle would
    overlap the body, and where a translucent colour is blended twice the
    join shows up as a seam along the top and bottom edges.
    """
    body, left, right = pill_geometry(center_x, center_y, width, height)
    if body[2] > 0:
        arcade.draw_rect_filled(arcade.XYWH(*body), color)

    diameter = height
    arcade.draw_arc_filled(left[0], left[1], diameter, diameter, color,
                           90, 270)
    arcade.draw_arc_filled(right[0], right[1], diameter, diameter, color,
                           270, 450)


def rounded_rect_geometry(left: float, bottom: float, right: float,
                          top: float, radius: float):
    """Return the parts that make up a rounded rectangle.

    Two overlapping rectangles and four corner quarters. The corners are
    quarter circles rather than whole ones for the same reason a pill's caps
    are halves: a translucent colour blended twice shows the join.

    Returns:
        ``(horizontal_rect, vertical_rect, corners)`` where each rect is
        ``(cx, cy, width, height)`` and each corner is
        ``(cx, cy, radius, start_angle, end_angle)`` in degrees.
    """
    width = max(right - left, 0.0)
    height = max(top - bottom, 0.0)
    radius = float(min(radius, width / 2.0, height / 2.0))

    horizontal = ((left + right) / 2.0, (bottom + top) / 2.0,
                  width, max(height - radius * 2.0, 0.0))
    vertical = ((left + right) / 2.0, (bottom + top) / 2.0,
                max(width - radius * 2.0, 0.0), height)

    corners = (
        (left + radius, bottom + radius, radius, 180.0, 270.0),
        (right - radius, bottom + radius, radius, 270.0, 360.0),
        (right - radius, top - radius, radius, 0.0, 90.0),
        (left + radius, top - radius, radius, 90.0, 180.0),
    )
    return horizontal, vertical, corners


def draw_rounded_rect(left: float, bottom: float, right: float, top: float,
                      radius: float, colour) -> None:
    """Fill a rounded rectangle in one flat tone."""
    horizontal, vertical, corners = rounded_rect_geometry(
        left, bottom, right, top, radius)

    if horizontal[3] > 0:
        arcade.draw_rect_filled(arcade.XYWH(*horizontal), colour)
    if vertical[2] > 0:
        arcade.draw_rect_filled(arcade.XYWH(*vertical), colour)
    for cx, cy, r, start, end in corners:
        if r > 0:
            arcade.draw_arc_filled(cx, cy, r * 2, r * 2, colour, start, end)


def draw_tray(center_x: float, center_y: float, width: float, height: float,
              fill=TRAY_FILL, border=TRAY_BORDER) -> None:
    """Draw a pill-shaped tray for grouping round buttons.

    The border is drawn as a slightly larger pill underneath rather than as
    an outline, since an outlined pill would need two arcs and two lines.
    """
    if border is not None:
        _fill_pill(center_x, center_y,
                   width + TRAY_BORDER_WIDTH * 2,
                   height + TRAY_BORDER_WIDTH * 2, border)
    _fill_pill(center_x, center_y, width, height, fill)
