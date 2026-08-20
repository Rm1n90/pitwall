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
