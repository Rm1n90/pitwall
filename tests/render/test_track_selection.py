"""Tests that clicking a car on the track picks the right driver."""

import pytest

pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.interfaces.race_replay import F1RaceReplayWindow  # noqa: E402


class FakeWindow:
    """Just enough of the replay window for the hit test to run.

    ``_driver_at`` only needs the current frame and the coordinate transform,
    so the real window, which needs a graphics context, is not required.
    """

    def __init__(self, drivers, scale=1.0):
        self.frames = [{"t": 0.0, "lap": 1, "drivers": drivers}]
        self.frame_index = 0
        self.n_frames = 1
        self._scale = scale

    def world_to_screen(self, x, y):
        return x * self._scale, y * self._scale


def car(x, y, **extra):
    entry = {"x": x, "y": y, "retired": False}
    entry.update(extra)
    return entry


def driver_at(window, x, y):
    return F1RaceReplayWindow._driver_at(window, x, y)


class TestClickingACar:
    def test_a_click_on_a_car_selects_that_driver(self):
        window = FakeWindow({"VER": car(100.0, 200.0)})
        assert driver_at(window, 100.0, 200.0) == "VER"

    def test_the_click_is_tested_in_screen_space(self):
        # The track is scaled to fit the window, so world coordinates alone
        # would pick the wrong car.
        window = FakeWindow({"VER": car(100.0, 200.0)}, scale=2.0)
        assert driver_at(window, 200.0, 400.0) == "VER"
        assert driver_at(window, 100.0, 200.0) is None

    def test_a_click_on_open_track_selects_nobody(self):
        window = FakeWindow({"VER": car(100.0, 200.0)})
        assert driver_at(window, 600.0, 600.0) is None

    def test_the_nearest_of_two_cars_wins(self):
        window = FakeWindow({"VER": car(100.0, 200.0),
                             "NOR": car(112.0, 200.0)})
        assert driver_at(window, 110.0, 200.0) == "NOR"

    def test_retired_cars_cannot_be_clicked(self):
        # They are no longer drawn, so clicking where they stopped should
        # not pick them.
        window = FakeWindow({"BOT": car(100.0, 200.0, retired=True)})
        assert driver_at(window, 100.0, 200.0) is None

    def test_a_car_without_a_position_is_skipped(self):
        window = FakeWindow({"VER": {"x": None, "y": None}})
        assert driver_at(window, 100.0, 200.0) is None

    def test_no_frames_means_nothing_to_click(self):
        window = FakeWindow({})
        window.frames = []
        assert driver_at(window, 100.0, 200.0) is None


class TestSelectionBehaviour:
    """A click on the track must behave exactly like a click on a tower row."""

    def _tower(self):
        from src.render.timing_tower import TimingTower
        return TimingTower(x=0)

    class Target:
        selected_drivers = []
        selected_driver = None

    def test_selecting_a_driver_tells_the_window(self):
        tower, window = self._tower(), self.Target()
        tower.select(window, "VER")

        assert window.selected_drivers == ["VER"]
        assert window.selected_driver == "VER"

    def test_selecting_the_same_driver_again_clears_it(self):
        tower, window = self._tower(), self.Target()
        tower.select(window, "VER")
        tower.select(window, "VER")

        assert window.selected_drivers == []
        assert window.selected_driver is None

    def test_selecting_another_driver_replaces_the_first(self):
        tower, window = self._tower(), self.Target()
        tower.select(window, "VER")
        tower.select(window, "NOR")

        assert window.selected_drivers == ["NOR"]

    def test_holding_shift_adds_to_the_selection(self):
        tower, window = self._tower(), self.Target()
        tower.select(window, "VER")
        tower.select(window, "NOR", multi=True)

        assert window.selected_drivers == ["VER", "NOR"]

    def test_holding_shift_on_a_selected_driver_removes_them(self):
        tower, window = self._tower(), self.Target()
        tower.select(window, "VER")
        tower.select(window, "NOR", multi=True)
        tower.select(window, "VER", multi=True)

        assert window.selected_drivers == ["NOR"]
