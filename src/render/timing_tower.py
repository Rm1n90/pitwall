"""The timing tower.

A broadcast timing tower answers, for every car at a glance: where it is, how
far behind, what it is running, how many stops it has made and how quick its
last lap was. The old leaderboard showed position and driver code only, and
re-sorted the field itself using lap and distance, which quietly threw away
the classification the frames already carry.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import arcade

from src.render.cars import compound_color

ROW_HEIGHT = 26
HEADER_HEIGHT = 46

# Column offsets from the left of the tower, in pixels.
COL_POSITION = 4
COL_CHANGE = 24
COL_CODE = 42
COL_GAP = 92
COL_TYRE = 158
COL_PITS = 200
COL_LAP = 222

BACKGROUND = (18, 19, 23, 210)
ROW_ALTERNATE = (26, 28, 34, 150)
SELECTED_ROW = (70, 74, 86, 235)
HEADER_COLOR = (150, 156, 170)
TEXT_COLOR = (232, 234, 240)
MUTED_COLOR = (140, 146, 160)

GAINED_COLOR = (86, 200, 110)
LOST_COLOR = (222, 92, 92)
PURPLE = (176, 84, 236)
PERSONAL_BEST = (86, 200, 110)
PIT_COLOR = (240, 176, 64)
RETIRED_COLOR = (150, 60, 60)

# Used when the leader's own lap time is not yet known.
FALLBACK_LAP_TIME_S = 92.0


def format_gap(gap_laps: float, reference_lap_s: float) -> str:
    """Render a gap expressed in laps as a readable string.

    Args:
        gap_laps: How far behind, measured in laps.
        reference_lap_s: Lap time used to convert a part-lap into seconds.
    """
    if gap_laps >= 1.0:
        whole = int(gap_laps)
        return f"+{whole} LAP" if whole == 1 else f"+{whole} LAPS"
    seconds = gap_laps * max(reference_lap_s, 1.0)
    if seconds < 0.05:
        return "—"
    return f"+{seconds:.3f}" if seconds < 10 else f"+{seconds:.1f}"


def format_lap_time(seconds: Optional[float]) -> str:
    """Render a lap time as ``m:ss.mmm``."""
    if seconds is None or seconds <= 0:
        return "—"
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    if minutes:
        return f"{minutes}:{remainder:06.3f}"
    return f"{remainder:.3f}"


class TimingTower:
    """Draws the running order with gaps, tyres, stops and lap times.

    Args:
        x: Left edge in pixels.
        width: Tower width in pixels.
        visible: Whether to draw at all.
    """

    def __init__(self, x: int, width: int = 260, visible: bool = True):
        self.x = x
        self.width = width
        self._visible = visible

        self.entries: List[Tuple] = []
        self.rects: List[Tuple] = []
        self.selected: List[str] = []

        #: ``{code: grid_position}``, for the places gained column.
        self.grid_positions: Dict[str, int] = {}
        #: ``{code: last_lap_seconds}``.
        self.last_laps: Dict[str, float] = {}
        #: Best lap of the session so far, and who set it.
        self.session_best: Optional[float] = None
        self.session_best_code: Optional[str] = None
        #: ``{code: personal_best_seconds}``.
        self.personal_bests: Dict[str, float] = {}
        #: Leader's most recent lap time, used to turn part-laps into seconds.
        self.reference_lap_s: float = FALLBACK_LAP_TIME_S

        self._row_text = arcade.Text("", 0, 0, TEXT_COLOR, 12)

    # -- state ------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = bool(value)

    def toggle_visibility(self) -> bool:
        self._visible = not self._visible
        return self._visible

    def set_visible(self) -> None:
        self._visible = True

    def set_entries(self, entries: Sequence[Tuple]) -> None:
        """Take ``(code, colour, car, progress)`` tuples for one frame."""
        self.entries = list(entries)

    def on_resize(self, window) -> None:
        self.x = max(20, window.width - window.right_ui_margin + 12)

    # -- drawing ----------------------------------------------------------

    def draw(self, window) -> None:
        if not self._visible or not self.entries:
            return

        self.selected = getattr(window, "selected_drivers", []) or []

        # The frames already carry the classification, which accounts for the
        # chequered flag; re-deriving it here would undo that.
        rows = sorted(self.entries,
                      key=lambda e: e[2].get("position") or 99)

        top = window.height - 40
        self._draw_header(top)
        self.rects = []

        body_top = top - HEADER_HEIGHT
        height = ROW_HEIGHT * len(rows)
        arcade.draw_lrbt_rectangle_filled(
            self.x - 6, self.x + self.width + 6,
            body_top - height, body_top, BACKGROUND)

        for index, (code, color, car, _progress) in enumerate(rows):
            self._draw_row(index, code, color, car, body_top, rows)

    def _draw_header(self, top: float) -> None:
        arcade.Text("TIMING", self.x, top, TEXT_COLOR, 15, bold=True,
                    anchor_x="left", anchor_y="top").draw()
        labels = ((COL_GAP, "GAP"), (COL_TYRE, "TYRE"),
                  (COL_PITS, "PIT"), (COL_LAP, "LAST"))
        for offset, label in labels:
            arcade.Text(label, self.x + offset, top - 24, HEADER_COLOR, 8,
                        bold=True, anchor_x="left", anchor_y="top").draw()

    def _draw_row(self, index: int, code: str, color, car: dict,
                  body_top: float, rows: Sequence) -> None:
        top = body_top - index * ROW_HEIGHT
        bottom = top - ROW_HEIGHT
        left, right = self.x - 6, self.x + self.width + 6
        self.rects.append((code, left, bottom, right, top))

        selected = code in self.selected
        if selected:
            arcade.draw_lrbt_rectangle_filled(left, right, bottom, top,
                                              SELECTED_ROW)
        elif index % 2:
            arcade.draw_lrbt_rectangle_filled(left, right, bottom, top,
                                              ROW_ALTERNATE)

        retired = bool(car.get("retired"))
        text_y = top - ROW_HEIGHT / 2
        base_color = MUTED_COLOR if retired else TEXT_COLOR

        # A team-coloured bar reads faster than coloured text.
        arcade.draw_lrbt_rectangle_filled(
            left, left + 3, bottom + 3, top - 3,
            (100, 100, 100) if retired else color[:3])

        self._text(str(car.get("position") or index + 1),
                   COL_POSITION + 6, text_y, base_color, 12, bold=True)
        self._draw_change(code, car, text_y)
        self._text(code, COL_CODE, text_y,
                   MUTED_COLOR if retired else color[:3], 13, bold=True)

        if retired:
            self._text("OUT", COL_GAP, text_y, RETIRED_COLOR, 11, bold=True)
        elif car.get("in_pit"):
            self._text("IN PIT", COL_GAP, text_y, PIT_COLOR, 11, bold=True)
        else:
            self._text(self._gap_text(index, rows), COL_GAP, text_y,
                       base_color, 11)

        self._draw_tyre(car, text_y, retired)

        stops = car.get("pit_stops")
        self._text("—" if stops is None else str(stops),
                   COL_PITS + 4, text_y, MUTED_COLOR, 11)

        self._draw_last_lap(code, text_y, retired)

    def _draw_change(self, code: str, car: dict, text_y: float) -> None:
        """Show places gained or lost against the starting grid."""
        grid = self.grid_positions.get(code)
        position = car.get("position")
        if not grid or not position:
            return
        delta = grid - position
        if delta == 0:
            self._text("·", COL_CHANGE + 4, text_y, MUTED_COLOR, 11)
            return
        color = GAINED_COLOR if delta > 0 else LOST_COLOR
        self._draw_arrow(self.x + COL_CHANGE + 3, text_y, delta > 0, color)
        self._text(str(abs(delta)), COL_CHANGE + 8, text_y, color, 9,
                   bold=True)

    @staticmethod
    def _draw_arrow(x: float, y: float, upwards: bool, color) -> None:
        """Draw a small triangle, since arrow glyphs are not always present."""
        size = 3.5
        tip = y + size if upwards else y - size
        base = y - size if upwards else y + size
        arcade.draw_triangle_filled(x, tip, x - size, base, x + size, base,
                                    color)

    def _gap_text(self, index: int, rows: Sequence) -> str:
        if index == 0:
            return "LEADER"
        leader_progress = rows[0][3]
        gap_laps = max(0.0, leader_progress - rows[index][3])
        return format_gap(gap_laps, self.reference_lap_s)

    def _draw_tyre(self, car: dict, text_y: float, retired: bool) -> None:
        compound = car.get("tyre")
        color = (110, 114, 126) if retired else compound_color(compound)
        arcade.draw_circle_filled(self.x + COL_TYRE + 6, text_y, 6, color)
        arcade.draw_circle_outline(self.x + COL_TYRE + 6, text_y, 6,
                                   (20, 21, 25), 1.4)
        try:
            age = int(float(car.get("tyre_life") or 0))
        except (TypeError, ValueError):
            age = 0
        self._text(str(age), COL_TYRE + 18, text_y, MUTED_COLOR, 10)

    def _draw_last_lap(self, code: str, text_y: float, retired: bool) -> None:
        last = self.last_laps.get(code)
        if last is None:
            self._text("—", COL_LAP, text_y, MUTED_COLOR, 10)
            return
        if self.session_best is not None and code == self.session_best_code \
                and abs(last - self.session_best) < 1e-6:
            color = PURPLE
        elif self.personal_bests.get(code) is not None \
                and abs(last - self.personal_bests[code]) < 1e-6:
            color = PERSONAL_BEST
        else:
            color = MUTED_COLOR if retired else TEXT_COLOR
        self._text(format_lap_time(last), COL_LAP, text_y, color, 10)

    def _text(self, value: str, offset: float, y: float, color,
              size: int, bold: bool = False) -> None:
        arcade.draw_text(value, self.x + offset, y, color, size,
                         anchor_x="left", anchor_y="center", bold=bold)

    # -- input ------------------------------------------------------------

    def on_mouse_press(self, window, x: float, y: float, button: int,
                       modifiers: int) -> bool:
        for code, left, bottom, right, top in self.rects:
            if left <= x <= right and bottom <= y <= top:
                multi = bool(modifiers & arcade.key.MOD_SHIFT)
                if multi:
                    if code in self.selected:
                        self.selected.remove(code)
                    else:
                        self.selected.append(code)
                elif self.selected == [code]:
                    self.selected = []
                else:
                    self.selected = [code]

                window.selected_drivers = self.selected
                window.selected_driver = \
                    self.selected[-1] if self.selected else None
                return True
        return False
