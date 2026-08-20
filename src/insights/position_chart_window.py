"""The race position chart.

Every driver's position plotted against lap number, so a whole race reads at a
glance: who came through the field, who fell back, and where the stops
happened. Positions come from the replay over the telemetry stream, and the
chart only draws up to the lap being replayed so it fills in as the race runs.
"""

import sys
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.gui.pit_wall_window import PitWallWindow

BACKGROUND = QColor("#0f1013")
GRID = QColor("#22242a")
AXIS_TEXT = QColor("#8a90a0")
DIMMED = QColor("#3a3d45")

MARGIN_LEFT = 54
MARGIN_RIGHT = 58
MARGIN_TOP = 18
MARGIN_BOTTOM = 34

LINE_WIDTH = 2.0
HIGHLIGHT_WIDTH = 3.4


class PositionChart(QWidget):
    """Draws the position lines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: Dict[str, List[Tuple[int, int]]] = {}
        self.colours: Dict[str, str] = {}
        self.total_laps = 0
        self.current_lap = 0
        self.follow_replay = True
        self.setMinimumSize(560, 360)

    def update_data(self, history, colours, total_laps, current_lap):
        self.history = history or {}
        self.colours = colours or {}
        self.total_laps = total_laps or 0
        self.current_lap = current_lap or 0
        self.update()

    def _visible_laps(self) -> int:
        if self.follow_replay and self.current_lap:
            return max(1, self.current_lap)
        return max(1, self.total_laps or self.current_lap or 1)

    def _grid_extent(self) -> Tuple[int, int]:
        """Return the lap and position extents the axes should cover."""
        laps = max(1, self.total_laps or self._visible_laps())
        positions = 1
        for entries in self.history.values():
            for _, position in entries:
                positions = max(positions, position)
        return laps, max(positions, 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)

        if not self.history:
            painter.setPen(AXIS_TEXT)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Waiting for the race to start...")
            return

        laps, places = self._grid_extent()
        left, right = MARGIN_LEFT, self.width() - MARGIN_RIGHT
        top, bottom = MARGIN_TOP, self.height() - MARGIN_BOTTOM
        if right <= left or bottom <= top:
            return

        def x_for(lap):
            return left + (right - left) * (lap - 1) / max(1, laps - 1)

        def y_for(position):
            return top + (bottom - top) * (position - 1) / max(1, places - 1)

        self._draw_grid(painter, laps, places, x_for, y_for, left, right,
                        top, bottom)
        self._draw_lines(painter, x_for, y_for)

    def _draw_grid(self, painter, laps, places, x_for, y_for,
                   left, right, top, bottom):
        painter.setFont(QFont("", 8))
        step = 5 if places <= 24 else 10
        for position in range(1, places + 1, 1):
            y = y_for(position)
            if position == 1 or position % step == 0:
                painter.setPen(QPen(GRID, 1))
                painter.drawLine(left, int(y), right, int(y))
                painter.setPen(AXIS_TEXT)
                painter.drawText(6, int(y) + 4, f"P{position}")

        lap_step = max(1, round(laps / 10 / 5) * 5) if laps > 10 else 1
        for lap in range(1, laps + 1):
            if lap != 1 and lap % lap_step:
                continue
            x = x_for(lap)
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(int(x), top, int(x), bottom)
            painter.setPen(AXIS_TEXT)
            painter.drawText(int(x) - 8, bottom + 16, str(lap))

        painter.setPen(AXIS_TEXT)
        painter.drawText(int((left + right) / 2) - 14, bottom + 30, "LAP")

    def _draw_lines(self, painter, x_for, y_for):
        limit = self._visible_laps()
        painter.setFont(QFont("", 8, QFont.Bold))

        for code, entries in sorted(self.history.items()):
            points = [(lap, position) for lap, position in entries
                      if lap <= limit]
            if len(points) < 2:
                continue

            colour = QColor(self.colours.get(code, "#9aa0ad"))
            painter.setPen(QPen(colour, LINE_WIDTH, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            previous = None
            for lap, position in points:
                current = (x_for(lap), y_for(position))
                if previous is not None:
                    painter.drawLine(int(previous[0]), int(previous[1]),
                                     int(current[0]), int(current[1]))
                previous = current

            # Label where each driver has got to.
            painter.setPen(colour)
            painter.drawText(int(previous[0]) + 6, int(previous[1]) + 4, code)


class PositionChartWindow(PitWallWindow):
    """Insight window showing the race position chart."""

    def setup_ui(self):
        self.setWindowTitle("Pitwall - Race Position Chart")
        self.resize(980, 620)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("Race Position Chart")
        title.setFont(QFont("", 13, QFont.Bold))
        header.addWidget(title)
        header.addStretch()

        self.follow_box = QCheckBox("Follow the replay")
        self.follow_box.setChecked(True)
        self.follow_box.stateChanged.connect(self._on_follow_changed)
        header.addWidget(self.follow_box)

        self.lap_label = QLabel("")
        self.lap_label.setStyleSheet("color: #8a90a0;")
        header.addWidget(self.lap_label)

        layout.addLayout(header)

        self.chart = PositionChart()
        layout.addWidget(self.chart)

        container.setStyleSheet("background-color: #0f1013; color: #e8eaf0;")
        self.setCentralWidget(container)

        self._history: Dict[str, List[Tuple[int, int]]] = {}
        self._colours: Dict[str, str] = {}
        self._total_laps = 0
        self._current_lap = 0

    def _on_follow_changed(self, _state):
        self.chart.follow_replay = self.follow_box.isChecked()
        self.chart.update()

    def on_telemetry_data(self, data):
        history = data.get("position_history")
        if history:
            self._history = {
                code: [(int(lap), int(position)) for lap, position in entries]
                for code, entries in history.items()
            }

        colours = data.get("driver_colors")
        if colours:
            self._colours = colours

        session = data.get("session_data") or {}
        self._total_laps = session.get("total_laps") or self._total_laps
        self._current_lap = session.get("lap") or self._current_lap

        if self._total_laps:
            self.lap_label.setText(
                f"Lap {self._current_lap} / {self._total_laps}")

        self.chart.update_data(self._history, self._colours,
                               self._total_laps, self._current_lap)


def main():
    app = QApplication(sys.argv)
    window = PositionChartWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
