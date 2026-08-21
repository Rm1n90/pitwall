"""Parsing the official Analysis PDF into per-rider, per-lap timing.

Validated against the 2025 Thailand MotoGP race, whose classification JSON is
the ground truth for how many laps each rider ran.
"""
import os

import pytest

from src.motogp import timing_pdf, models

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")
ANALYSIS = os.path.join(FIXTURES, "THA_2025_MotoGP_RAC_Analysis.pdf")

# The Analysis PDF is Dorna copyright and not committed; fetch it with
# tests/fixtures/motogp/download_pdfs.py to run these tests.
pytestmark = pytest.mark.skipif(
    not os.path.exists(ANALYSIS),
    reason="Analysis PDF fixture absent; run download_pdfs.py")


@pytest.fixture(scope="module")
def sheet():
    return timing_pdf.parse_analysis(ANALYSIS)


def test_winner_has_all_laps_with_sectors(sheet):
    marc = sheet.by_number(93)
    assert marc is not None
    assert marc.surname.upper() == "MARQUEZ"
    # Marc Marquez ran 26 laps in the race.
    assert len(marc.laps) == 26
    # His fastest lap was lap 4, 1'30.637, split 18.618 / 25.801 / 23.044 / 23.174.
    lap4 = next(l for l in marc.laps if l.number == 4)
    assert lap4.lap_time_s == pytest.approx(90.637, abs=0.002)
    assert lap4.sectors[0] == pytest.approx(18.618, abs=0.002)
    assert lap4.sectors[1] == pytest.approx(25.801, abs=0.002)
    assert lap4.sectors[2] == pytest.approx(23.044, abs=0.002)
    assert lap4.sectors[3] == pytest.approx(23.174, abs=0.002)
    # Sectors sum to the lap time.
    assert sum(lap4.sectors) == pytest.approx(lap4.lap_time_s, abs=0.01)
    # Speed trap is captured.
    assert 300 < lap4.speed_kmh < 360


def test_tyre_compounds_captured(sheet):
    marc = sheet.by_number(93)
    assert "Soft" in marc.front_tyre
    assert "Medium" in marc.rear_tyre


def test_lap_counts_match_classification(sheet):
    """Every finisher's parsed lap count matches the official classification."""
    import json
    with open(os.path.join(FIXTURES, "classification_race.json")) as handle:
        rows = models.parse_classification(json.load(handle))

    checked = 0
    for row in rows:
        if row.total_laps is None or row.rider_number is None:
            continue
        rider = sheet.by_number(row.rider_number)
        assert rider is not None, f"missing rider #{row.rider_number} in sheet"
        # The Analysis sheet lists every lap the rider completed, which equals
        # the classified total lap count.
        assert len(rider.laps) == row.total_laps, (
            f"#{row.rider_number} {row.rider_name}: "
            f"parsed {len(rider.laps)} != official {row.total_laps}")
        checked += 1
    assert checked >= 18


def test_all_riders_present(sheet):
    # A MotoGP grid is ~22 riders; every one appears in the analysis.
    assert len(sheet.riders) >= 20
