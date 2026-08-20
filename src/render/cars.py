"""Drawing the cars.

A car used to be a six pixel dot in the driver's team colour. It is now a
marker that carries what you actually want to know at a glance: whose car it
is, what tyre it is on, whether DRS is open, whether it is in the pits, and
whether you have selected it.
"""

import math
from typing import Tuple

import arcade

# Radii in pixels.
BODY_RADIUS = 6.5
OUTLINE_WIDTH = 1.6
TYRE_RING_WIDTH = 2.2
SELECTED_RING_RADIUS = 13.0

# A dark ring around every car keeps team colours legible against asphalt.
OUTLINE_COLOR = (12, 13, 16)
LEADER_RING_COLOR = (255, 215, 0)
DRS_GLOW_COLOR = (0, 220, 120)
PIT_COLOR = (150, 155, 168)

# Tyre compounds, matching the integers used throughout the frame data.
COMPOUND_COLORS = {
    0: (214, 44, 44),      # soft
    1: (226, 190, 60),     # medium
    2: (232, 232, 236),    # hard
    3: (60, 168, 84),      # intermediate
    4: (48, 128, 220),     # wet
}
UNKNOWN_COMPOUND_COLOR = (110, 114, 126)


def compound_color(compound) -> Tuple[int, int, int]:
    """Return the colour for a tyre compound integer."""
    try:
        return COMPOUND_COLORS.get(int(compound), UNKNOWN_COMPOUND_COLOR)
    except (TypeError, ValueError):
        return UNKNOWN_COMPOUND_COLOR


def draw_car(screen_x: float, screen_y: float, color, car: dict,
             is_leader: bool = False, is_selected: bool = False) -> None:
    """Draw one car marker.

    Args:
        screen_x: Screen position.
        screen_y: Screen position.
        color: The driver's team colour.
        car: The driver's entry from the frame.
        is_leader: Whether this car leads the session.
        is_selected: Whether the viewer has picked this car out.
    """
    in_pit = bool(car.get("in_pit"))

    if is_selected:
        arcade.draw_circle_outline(
            screen_x, screen_y, SELECTED_RING_RADIUS, (255, 255, 255, 150), 1.5)

    # An open rear wing is worth spotting from across the map.
    if car.get("drs") in (10, 12, 14):
        arcade.draw_circle_filled(
            screen_x, screen_y, BODY_RADIUS + 5, (*DRS_GLOW_COLOR, 70))

    if is_leader:
        arcade.draw_circle_outline(
            screen_x, screen_y, BODY_RADIUS + 3.4, LEADER_RING_COLOR, 1.8)

    # The tyre ring doubles as the outline, so the marker stays compact.
    ring = PIT_COLOR if in_pit else compound_color(car.get("tyre"))
    arcade.draw_circle_outline(
        screen_x, screen_y, BODY_RADIUS + 1.6, ring, TYRE_RING_WIDTH)
    arcade.draw_circle_outline(
        screen_x, screen_y, BODY_RADIUS + 0.4, OUTLINE_COLOR, OUTLINE_WIDTH)

    body = tuple(int(c * 0.45) for c in color[:3]) if in_pit else color
    arcade.draw_circle_filled(screen_x, screen_y, BODY_RADIUS, body)


def draw_label(screen_x: float, screen_y: float, code: str, color,
               normal: Tuple[float, float], distance: float = 34.0) -> None:
    """Draw a driver code on a leader line pointing away from the track."""
    nx, ny = normal
    end_x = screen_x + nx * distance
    end_y = screen_y + ny * distance
    arcade.draw_line(screen_x, screen_y, end_x, end_y, (*color[:3], 170), 1.2)

    anchor = "left" if nx >= 0 else "right"
    padding = 4 if nx >= 0 else -4
    arcade.draw_text(code, end_x + padding, end_y, color, 10,
                     anchor_x=anchor, anchor_y="center", bold=True)


def draw_safety_car(screen_x: float, screen_y: float, phase: str,
                    alpha: float, pulse_phase: float = 0.0) -> None:
    """Draw the simulated safety car."""
    alpha = max(0.0, min(1.0, float(alpha)))
    body_alpha = int(255 * max(0.1, alpha))

    if phase in ("deploying", "returning"):
        pulse = 0.5 + 0.5 * math.sin(pulse_phase * 8.0)
        radius = 16 + pulse * 6
        glow = int(80 * alpha * pulse)
        arcade.draw_circle_filled(screen_x, screen_y, radius, (255, 200, 0, glow))
        arcade.draw_circle_outline(
            screen_x, screen_y, radius + 2, (255, 100, 0, int(glow * 0.6)), 2)
    else:
        arcade.draw_circle_filled(screen_x, screen_y, 14, (255, 165, 0, 40))

    arcade.draw_circle_filled(screen_x, screen_y, 8, (255, 165, 0, body_alpha))
    arcade.draw_circle_outline(
        screen_x, screen_y, 9, (255, 100, 0, int(255 * alpha)), 2)
    arcade.draw_text("SC", screen_x + 14, screen_y + 2,
                     (255, 255, 255, int(255 * max(0.3, alpha))), 11,
                     anchor_x="left", anchor_y="center", bold=True)

    caption = {"deploying": "SC DEPLOYING", "returning": "SC IN"}.get(phase)
    if caption:
        arcade.draw_text(caption, screen_x, screen_y - 18,
                         (255, 200, 0, int(200 * alpha)), 8,
                         anchor_x="center", anchor_y="top", bold=True)
