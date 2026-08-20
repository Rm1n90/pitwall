"""One place for how the interface looks.

Panels were each styled where they were drawn, so the weather read as plain
text on the track while the timing tower had a background and the driver
panel had a border. These are the tokens they all share: the same surface,
the same edge, the same text colours and the same corner radius, so the
screen looks like one thing rather than several.
"""

from src.render.shapes import draw_rounded_rect

# Surfaces, from the page backwards.
SURFACE = (18, 19, 24, 214)
SURFACE_RAISED = (26, 28, 34, 226)
SURFACE_EDGE = (255, 255, 255, 26)

# Text, in the order you should notice it.
TEXT = (232, 234, 240)
TEXT_MUTED = (146, 152, 166)
TEXT_DIM = (104, 110, 124)

# Meaning, not decoration.
ACCENT = (94, 174, 255)
POSITIVE = (86, 200, 110)
WARNING = (240, 176, 64)
DANGER = (222, 92, 92)
PURPLE = (176, 84, 236)

# Type scale. Panels use the same handful of sizes rather than a new one
# each time something is added.
SIZE_TITLE = 15
SIZE_HEADING = 13
SIZE_BODY = 12
SIZE_SMALL = 11
SIZE_TINY = 9

# Spacing, in pixels.
PAD = 14
GAP = 10
ROW = 22

CORNER_RADIUS = 10
EDGE_WIDTH = 1.5


def draw_panel(left: float, bottom: float, right: float, top: float,
               fill=SURFACE, edge=SURFACE_EDGE,
               radius: float = CORNER_RADIUS) -> None:
    """Draw the surface every panel sits on.

    The edge is a slightly larger panel drawn underneath rather than an
    outline, which keeps it a single flat tone at the corners.
    """
    if edge is not None:
        draw_rounded_rect(left - EDGE_WIDTH, bottom - EDGE_WIDTH,
                          right + EDGE_WIDTH, top + EDGE_WIDTH,
                          radius + EDGE_WIDTH, edge)
    draw_rounded_rect(left, bottom, right, top, radius, fill)
