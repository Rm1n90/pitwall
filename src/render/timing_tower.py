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

# Column offsets from the left of the tower, in pixels. They are spaced by
# what the widest value in each column actually measures, not by eye: a
# two-digit position and a three-letter code are wider than they look, and at
# the old spacing the position ran into the change arrow and the code ran
# into the sector bars, so HAD read as HAI.
TOWER_WIDTH = 384

COL_POSITION = 4
COL_CHANGE = 30
COL_CODE = 58
COL_SECTORS = 116
COL_GAP = 152
COL_TYRE = 212
COL_PITS = 254
COL_STOP = 282
COL_LAP = 320

# The widest thing each column ever has to draw, measured at the font size
# and weight it is drawn in. Used by the tests that guard the spacing.
COLUMN_CONTENT_WIDTHS = {
    COL_POSITION: 24,   # "22" at 12pt bold, plus its 6px indent
    COL_CHANGE: 22,     # arrow plus "12" at 9pt bold
    COL_CODE: 51,       # "WWW" at 13pt bold
    COL_SECTORS: 30,    # three bars and their gaps
    COL_GAP: 53,        # "LEADER" at 11pt
    COL_TYRE: 40,       # the compound circle plus "28"
    COL_PITS: 17,       # the "PIT" heading, wider than the count below it
    COL_STOP: 28,       # "25.4" at 10pt
    COL_LAP: 56,        # "1:30.286" at 10pt
}

# Practice has no grid to compare against and no stops worth counting, so
# the columns freed up go to the driver's best lap and how many laps they
# have run.
PRACTICE_COL_CODE = 36
PRACTICE_COL_SECTORS = 96
PRACTICE_COL_BEST = 134
PRACTICE_COL_GAP = 200
PRACTICE_COL_TYRE = 266
PRACTICE_COL_LAPS = 316

PRACTICE_COLUMN_CONTENT_WIDTHS = {
    COL_POSITION: 24,
    PRACTICE_COL_CODE: 51,
    PRACTICE_COL_SECTORS: 30,
    PRACTICE_COL_BEST: 56,    # "1:19.075" at 10pt
    # The quickest driver's gap column shows their own lap time rather than
    # a delta, so it is as wide as the best-lap column beside it.
    PRACTICE_COL_GAP: 56,
    PRACTICE_COL_TYRE: 40,
    PRACTICE_COL_LAPS: 20,    # "30" at 11pt
}

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

# Sector status, in the order the lap history reports it.
SECTOR_COLORS = ((214, 200, 60), (86, 200, 110), (176, 84, 236))
SECTOR_BAR_WIDTH = 7
SECTOR_BAR_GAP = 3
SECTOR_BAR_HEIGHT = 4

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


def format_practice_gap(best_s: Optional[float],
                        session_best_s: Optional[float]) -> str:
    """Render a practice gap: the leader's own time, everyone else's delta."""
    if best_s is None or best_s <= 0:
        return "—"
    if session_best_s is None or best_s <= session_best_s:
        return format_lap_time(best_s)
    return f"+{best_s - session_best_s:.3f}"


class TimingTower:
    """Draws the running order with gaps, tyres, stops and lap times.

    Args:
        x: Left edge in pixels.
        width: Tower width in pixels.
        visible: Whether to draw at all.
    """

    def __init__(self, x: int, width: int = TOWER_WIDTH,
                 visible: bool = True):
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
        #: ``{code: [PitStop, ...]}``, for the stationary time in the box.
        self.pit_times: Dict[str, List] = {}
        #: ``{code: [s1, s2, s3]}`` status of each driver's last sectors.
        self.sectors: Dict[str, List[int]] = {}
        #: Leader's most recent lap time, used to turn part-laps into seconds.
        self.reference_lap_s: float = FALLBACK_LAP_TIME_S
        #: Practice is ranked on lap times, so it needs different columns.
        self.practice_mode: bool = False

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

    def header_labels(self):
        """Column offsets and headings for the mode the tower is in."""
        if self.practice_mode:
            return ((PRACTICE_COL_SECTORS, "SECT"),
                    (PRACTICE_COL_BEST, "BEST"),
                    (PRACTICE_COL_GAP, "GAP"),
                    (PRACTICE_COL_TYRE, "TYRE"),
                    (PRACTICE_COL_LAPS, "LAPS"))
        return ((COL_SECTORS, "SECT"), (COL_GAP, "GAP"),
                (COL_TYRE, "TYRE"), (COL_PITS, "PIT"),
                (COL_STOP, "STOP"), (COL_LAP, "LAST"))

    def _draw_header(self, top: float) -> None:
        arcade.Text("TIMING", self.x, top, TEXT_COLOR, 15, bold=True,
                    anchor_x="left", anchor_y="top").draw()
        for offset, label in self.header_labels():
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

        if self.practice_mode:
            self._draw_practice_columns(code, color, car, text_y)
            return

        self._draw_change(code, car, text_y)
        self._text(code, COL_CODE, text_y,
                   MUTED_COLOR if retired else color[:3], 13, bold=True)
        self._draw_sectors(code, text_y, retired)

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
        self._draw_stop_time(code, car, text_y)

        self._draw_last_lap(code, text_y, retired)

    def _draw_practice_columns(self, code: str, color, car: dict,
                               text_y: float) -> None:
        """Draw the columns a practice timing screen shows.

        There is no grid to have gained places against and no stops worth
        counting, so the row carries the driver's best lap, how far off the
        session best that is, and how many laps they have run.
        """
        in_pit = bool(car.get("in_pit"))
        self._text(code, PRACTICE_COL_CODE, text_y,
                   PIT_COLOR if in_pit else color[:3], 13, bold=True)
        self._draw_sectors(code, text_y, retired=False,
                           offset=PRACTICE_COL_SECTORS)

        best = self.personal_bests.get(code)
        if best is not None and self.session_best is not None \
                and abs(best - self.session_best) < 1e-6:
            best_color = PURPLE
        else:
            best_color = TEXT_COLOR if best is not None else MUTED_COLOR
        self._text(format_lap_time(best), PRACTICE_COL_BEST, text_y,
                   best_color, 10)

        if in_pit:
            self._text("IN PIT", PRACTICE_COL_GAP, text_y, PIT_COLOR, 10,
                       bold=True)
        else:
            self._text(format_practice_gap(best, self.session_best),
                       PRACTICE_COL_GAP, text_y,
                       best_color if best_color is PURPLE else MUTED_COLOR,
                       10)

        self._draw_tyre(car, text_y, retired=False, offset=PRACTICE_COL_TYRE)

        # The lap the car is on, which the frames carry exactly. Counting
        # completed lap times instead loses the in-lap back to the garage.
        laps = car.get("lap")
        self._text("—" if not laps else str(int(laps)),
                   PRACTICE_COL_LAPS, text_y, MUTED_COLOR, 11)

    def _draw_sectors(self, code: str, text_y: float, retired: bool,
                      offset: int = COL_SECTORS) -> None:
        """Draw three bars showing how the driver's last sectors went.

        Purple for the fastest anyone has managed, green for the driver's own
        best, and yellow otherwise, as a broadcast tower shows them.
        """
        statuses = self.sectors.get(code) or [0, 0, 0]
        for index, status in enumerate(statuses[:3]):
            left = self.x + offset + index * (
                SECTOR_BAR_WIDTH + SECTOR_BAR_GAP)
            try:
                color = SECTOR_COLORS[int(status)]
            except (TypeError, ValueError, IndexError):
                color = SECTOR_COLORS[0]
            if retired:
                color = (70, 72, 80)
            arcade.draw_lrbt_rectangle_filled(
                left, left + SECTOR_BAR_WIDTH,
                text_y - SECTOR_BAR_HEIGHT / 2,
                text_y + SECTOR_BAR_HEIGHT / 2, color)

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

    def _draw_tyre(self, car: dict, text_y: float, retired: bool,
                   offset: int = COL_TYRE) -> None:
        compound = car.get("tyre")
        color = (110, 114, 126) if retired else compound_color(compound)
        arcade.draw_circle_filled(self.x + offset + 6, text_y, 6, color)
        arcade.draw_circle_outline(self.x + offset + 6, text_y, 6,
                                   (20, 21, 25), 1.4)
        try:
            age = int(float(car.get("tyre_life") or 0))
        except (TypeError, ValueError):
            age = 0
        self._text(str(age), offset + 18, text_y, MUTED_COLOR, 10)

    def latest_stop(self, code: str, lap: Optional[int]):
        """Return the driver's most recent completed stop, if any."""
        stops = self.pit_times.get(code)
        if not stops:
            return None
        if lap is None:
            return stops[-1]
        done = [s for s in stops if s.lap is None or s.lap <= lap]
        return done[-1] if done else None

    def _draw_stop_time(self, code: str, car: dict, text_y: float) -> None:
        """Show how long the driver's last stop actually took."""
        try:
            lap = int(car.get("lap"))
        except (TypeError, ValueError):
            lap = None
        stop = self.latest_stop(code, lap)
        if stop is None or stop.stationary_s is None:
            self._text("—", COL_STOP + 4, text_y, MUTED_COLOR, 10)
            return
        self._text(f"{stop.stationary_s:.1f}", COL_STOP, text_y,
                   PIT_COLOR, 10)

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
                self.select(window, code,
                            multi=bool(modifiers & arcade.key.MOD_SHIFT))
                return True
        return False

    def select(self, window, code: str, multi: bool = False) -> None:
        """Add, remove or replace the selection, and tell the window.

        Clicking a car on the track goes through here too, so selecting a
        driver behaves the same wherever you click.
        """
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
