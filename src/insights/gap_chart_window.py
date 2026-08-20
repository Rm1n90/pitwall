"""The gap chart.

A position chart says who is where. This says how much time is between them,
which is what actually decides whether a move is coming: a gap coming down by
three tenths a lap is a pass in six laps, and a gap holding steady is a train.

Each driver's gap to the leader is plotted against lap number. Cars a lap down
have no gap in seconds, so their line simply stops.
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
LEADER_LINE = QColor("#3c4048")

MARGIN_LEFT = 62
MARGIN_RIGHT = 58
MARGIN_TOP = 18
MARGIN_BOTTOM = 34

LINE_WIDTH = 2.0

# The axis is drawn in six divisions, so its top is six times one of these.
# Anything else and the labels come out as +43s and +85s.
AXIS_DIVISIONS = 6
DIVISION_STEPS_S = (1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300)


def axis_maximum(widest_gap_s: float) -> float:
    """Round a gap up to an axis top that labels in round numbers."""
    for step in DIVISION_STEPS_S:
        if widest_gap_s <= step * AXIS_DIVISIONS:
            return float(step * AXIS_DIVISIONS)
    largest = DIVISION_STEPS_S[-1]
    steps = -(-widest_gap_s // (largest * AXIS_DIVISIONS))
    return float(largest * AXIS_DIVISIONS * steps)


class GapChart(QWidget):
    """Draws the gap lines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: Dict[str, List[Tuple[int, float]]] = {}
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

    def _grid_extent(self) -> Tuple[int, float]:
        """Return the lap and gap extents the axes should cover."""
        laps = max(1, self.total_laps or self._visible_laps())
        limit = self._visible_laps()
        widest = 0.0
        for entries in self.history.values():
            for lap, gap in entries:
                if lap <= limit:
                    widest = max(widest, gap)
        return laps, axis_maximum(max(widest, 1.0))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BACKGROUND)

        if not self.history:
            painter.setPen(AXIS_TEXT)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Waiting for the race to start...")
            return

        laps, widest = self._grid_extent()
        left, right = MARGIN_LEFT, self.width() - MARGIN_RIGHT
        top, bottom = MARGIN_TOP, self.height() - MARGIN_BOTTOM
        if right <= left or bottom <= top:
            return

        def x_for(lap):
            return left + (right - left) * (lap - 1) / max(1, laps - 1)

        def y_for(gap):
            return top + (bottom - top) * min(gap, widest) / widest

        self._draw_grid(painter, laps, widest, x_for, y_for, left, right,
                        top, bottom)
        self._draw_lines(painter, x_for, y_for, widest)

    def _draw_grid(self, painter, laps, widest, x_for, y_for,
                   left, right, top, bottom):
        painter.setFont(QFont("", 8))
        for step in range(AXIS_DIVISIONS + 1):
            gap = widest * step / AXIS_DIVISIONS
            y = y_for(gap)
            painter.setPen(QPen(LEADER_LINE if step == 0 else GRID, 1))
            painter.drawLine(left, int(y), right, int(y))
            painter.setPen(AXIS_TEXT)
            label = "LEADER" if step == 0 else f"+{gap:.0f}s"
            painter.drawText(6, int(y) + 4, label)

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

    def _draw_lines(self, painter, x_for, y_for, widest):
        limit = self._visible_laps()
        painter.setFont(QFont("", 8, QFont.Bold))

        for code, entries in sorted(self.history.items()):
            points = [(lap, gap) for lap, gap in entries if lap <= limit]
            if len(points) < 2:
                continue

            colour = QColor(self.colours.get(code, "#9aa0ad"))
            painter.setPen(QPen(colour, LINE_WIDTH, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            previous = None
            for lap, gap in points:
                current = (x_for(lap), y_for(gap))
                if previous is not None:
                    painter.drawLine(int(previous[0]), int(previous[1]),
                                     int(current[0]), int(current[1]))
                previous = current

            # Only label cars still on the chart, or the names pile up along
            # the bottom edge.
            if points[-1][1] <= widest:
                painter.setPen(colour)
                painter.drawText(int(previous[0]) + 6, int(previous[1]) + 4,
                                 code)


class GapChartWindow(PitWallWindow):
    """Insight window showing the gap to the leader over a race."""

    def setup_ui(self):
        self.setWindowTitle("Pitwall - Gap Chart")
        self.resize(980, 620)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("Gap to Leader")
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

        self.chart = GapChart()
        layout.addWidget(self.chart)

        container.setStyleSheet("background-color: #0f1013; color: #e8eaf0;")
        self.setCentralWidget(container)

        self._history: Dict[str, List[Tuple[int, float]]] = {}
        self._colours: Dict[str, str] = {}
        self._total_laps = 0
        self._current_lap = 0

    def _on_follow_changed(self, _state):
        self.chart.follow_replay = self.follow_box.isChecked()
        self.chart.update()

    def on_telemetry_data(self, data):
        history = data.get("gap_history")
        if history:
            self._history = {
                code: [(int(lap), float(gap)) for lap, gap in entries]
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
        elif self._current_lap:
            self.lap_label.setText(f"Lap {self._current_lap}")

        self.chart.update_data(self._history, self._colours,
                               self._total_laps, self._current_lap)


def main():
    app = QApplication(sys.argv)
    window = GapChartWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
