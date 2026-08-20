"""Tests for car marker styling."""

import pytest

pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.render.cars import (  # noqa: E402
    COMPOUND_COLORS,
    UNKNOWN_COMPOUND_COLOR,
    compound_color,
)


class TestCompoundColor:
    @pytest.mark.parametrize("compound", sorted(COMPOUND_COLORS))
    def test_every_compound_has_its_own_colour(self, compound):
        assert compound_color(compound) == COMPOUND_COLORS[compound]

    def test_compounds_are_visually_distinct(self):
        assert len(set(COMPOUND_COLORS.values())) == len(COMPOUND_COLORS)

    def test_a_float_compound_is_accepted(self):
        # Frames carry the compound as a float.
        assert compound_color(1.0) == COMPOUND_COLORS[1]

    @pytest.mark.parametrize("value", [None, "SOFT", -1, 99])
    def test_an_unknown_compound_falls_back(self, value):
        assert compound_color(value) == UNKNOWN_COMPOUND_COLOR


class TestDriverAt:
    """Clicking a car on the track should select it, as clicking a row does."""

    def test_a_click_on_a_car_finds_it(self):
        from src.render.cars import driver_at
        assert driver_at([("VER", 100.0, 200.0)], 100.0, 200.0) == "VER"

    def test_a_click_near_a_car_still_finds_it(self):
        # The car is a small dot, so the target has to be forgiving.
        from src.render.cars import driver_at
        assert driver_at([("VER", 100.0, 200.0)], 108.0, 205.0) == "VER"

    def test_a_click_on_empty_track_finds_nothing(self):
        from src.render.cars import driver_at
        assert driver_at([("VER", 100.0, 200.0)], 400.0, 400.0) is None

    def test_the_nearest_car_wins_in_a_pack(self):
        # At the start the whole field is within a few pixels of each other.
        from src.render.cars import driver_at
        cars = [("VER", 100.0, 200.0), ("NOR", 108.0, 200.0),
                ("LEC", 116.0, 200.0)]
        assert driver_at(cars, 107.0, 200.0) == "NOR"

    def test_cars_without_a_position_are_ignored(self):
        from src.render.cars import driver_at
        assert driver_at([("VER", None, None)], 100.0, 200.0) is None

    def test_an_empty_field_finds_nothing(self):
        from src.render.cars import driver_at
        assert driver_at([], 100.0, 200.0) is None

    def test_the_radius_can_be_tightened(self):
        from src.render.cars import driver_at
        cars = [("VER", 100.0, 200.0)]
        assert driver_at(cars, 112.0, 200.0, radius=4.0) is None
