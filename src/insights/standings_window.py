"""Championship standings.

The timing feed says nothing about the championship, only about the session in
front of you. This shows where the season stands, and while a race is running,
where it would stand if the race ended now.
"""

import sys
from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.pit_wall_window import PitWallWindow
from src.lib.standings import fetch_standings

GAINED = QColor("#56c86e")
LOST = QColor("#de5c5c")
MUTED = QColor("#8a90a0")


def _item(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None):
    cell = QTableWidgetItem(str(text))
    cell.setTextAlignment(align)
    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
    if color is not None:
        cell.setForeground(color)
    return cell


class StandingsTable(QTableWidget):
    """A championship table, optionally showing a projected position."""

    def __init__(self, headers, widths, parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setShowGrid(False)
        # Fixed widths: the projection column has the longest text and was
        # being clipped when the table shared them out on its own.
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)


class StandingsWindow(PitWallWindow):
    """Insight window showing the drivers' and constructors' championships."""

    def setup_ui(self):
        self.setWindowTitle("Pitwall - Championship Standings")
        self.resize(1020, 620)

        container = QWidget()
        layout = QVBoxLayout(container)

        header = QHBoxLayout()
        title = QLabel("Championship Standings")
        title.setFont(QFont("", 13, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        self.note = QLabel("")
        self.note.setStyleSheet("color: #8a90a0;")
        header.addWidget(self.note)
        layout.addLayout(header)

        tables = QHBoxLayout()
        self.drivers = StandingsTable(
            ["", "Driver", "Team", "Pts", "Wins", "If race ends now"],
            [34, 62, 130, 54, 46, 132])
        self.teams = StandingsTable(
            ["", "Constructor", "Pts", "Wins"], [34, 140, 54, 46])
        tables.addWidget(self.drivers, 3)
        tables.addWidget(self.teams, 2)
        layout.addLayout(tables)

        container.setStyleSheet(
            "background-color: #0f1013; color: #e8eaf0;"
            "QHeaderView::section { background-color: #16181d; }")
        self.setCentralWidget(container)

        self._prediction: Dict[str, dict] = {}
        self._year = None
        self._loaded_for = None

    # -- data -------------------------------------------------------------

    def _load(self, year: int) -> None:
        """Fetch and show the standings for a season."""
        if self._loaded_for == year:
            return
        self._loaded_for = year

        drivers = fetch_standings(year, "driver")
        teams = fetch_standings(year, "constructor")
        if not drivers and not teams:
            self.note.setText("Standings unavailable")
            return

        self.note.setText(f"{year} season")
        self._fill_drivers(drivers)
        self._fill_teams(teams)

    def _fill_drivers(self, standings: List) -> None:
        self.drivers.setRowCount(len(standings))
        for row, entry in enumerate(standings):
            self.drivers.setItem(row, 0, _item(entry.position,
                                               Qt.AlignCenter))
            self.drivers.setItem(row, 1, _item(entry.name))
            self.drivers.setItem(row, 2, _item(entry.team, color=MUTED))
            self.drivers.setItem(row, 3, _item(f"{entry.points:g}",
                                               Qt.AlignRight | Qt.AlignVCenter))
            self.drivers.setItem(row, 4, _item(entry.wins, Qt.AlignCenter))
            self.drivers.setItem(row, 5, self._projection_cell(entry))

    def _projection_cell(self, entry) -> QTableWidgetItem:
        """Show where this driver would end up if the race finished now."""
        predicted = None
        for row in self._prediction.values():
            if str(row.get("code") or "") == entry.name:
                predicted = row.get("predicted_position")
                break
        if predicted is None:
            return _item("", Qt.AlignCenter)

        try:
            predicted = int(predicted)
        except (TypeError, ValueError):
            return _item("", Qt.AlignCenter)

        delta = entry.position - predicted
        if delta > 0:
            return _item(f"P{predicted}  (+{delta})", Qt.AlignCenter, GAINED)
        if delta < 0:
            return _item(f"P{predicted}  ({delta})", Qt.AlignCenter, LOST)
        return _item(f"P{predicted}", Qt.AlignCenter, MUTED)

    def _fill_teams(self, standings: List) -> None:
        self.teams.setRowCount(len(standings))
        for row, entry in enumerate(standings):
            self.teams.setItem(row, 0, _item(entry.position, Qt.AlignCenter))
            self.teams.setItem(row, 1, _item(entry.name))
            self.teams.setItem(row, 2, _item(f"{entry.points:g}",
                                             Qt.AlignRight | Qt.AlignVCenter))
            self.teams.setItem(row, 3, _item(entry.wins, Qt.AlignCenter))

    # -- stream -----------------------------------------------------------

    def on_telemetry_data(self, data):
        session = data.get("session_data") or {}
        year = session.get("year") or data.get("season")
        if year and year != self._year:
            self._year = int(year)
            self._load(self._year)

        prediction = data.get("championship_prediction")
        if prediction:
            self._prediction = prediction.get("drivers") or {}
            if self._loaded_for:
                self._fill_drivers(fetch_standings(self._loaded_for, "driver"))


def main():
    app = QApplication(sys.argv)
    window = StandingsWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
