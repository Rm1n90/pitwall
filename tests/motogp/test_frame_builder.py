"""Turning per-lap sector times into a position-over-time replay."""
import json
import os

import numpy as np
import pytest

from src.motogp import frame_builder, geometry, timing_pdf, models
from src.motogp.timing_pdf import AnalysisSheet, RiderLaps, Lap

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")
_ANALYSIS_PDF = os.path.join(FIXTURES, "THA_2025_MotoGP_RAC_Analysis.pdf")


def _square_circuit(length_m=400.0):
    # A closed square; arc length is scaled to length_m by the geometry code.
    return geometry.circuit_from_path(
        "M0,0 L100,0 L100,100 L0,100 Z", length_m=length_m)


def _rider(number, sector_time, laps=2, surname="X"):
    """A rider whose every sector takes the same time (constant pace)."""
    lap_list = []
    for n in range(1, laps + 1):
        lap_list.append(Lap(number=n, lap_time_s=sector_time * 4,
                             sectors=[sector_time] * 4, speed_kmh=300.0))
    return RiderLaps(number=number, name="", surname=surname, constructor=None,
                     nation=None, front_tyre=None, rear_tyre=None, laps=lap_list)


def test_frames_span_the_race_at_the_given_rate():
    circuit = _square_circuit()
    sheet = AnalysisSheet(riders=[_rider(1, 5.0)])  # 2 laps * 20s = 40s
    result = frame_builder.build_race_frames(sheet, circuit, fps=25)
    frames = result["frames"]
    # 40 seconds at 25 fps, inclusive of the final frame.
    assert 1000 <= len(frames) <= 1002
    assert result["total_laps"] == 2
    assert result["session_type"] == "R"


def test_faster_rider_leads_and_laps_progress():
    circuit = _square_circuit(length_m=400.0)
    sheet = AnalysisSheet(riders=[_rider(1, 5.0, surname="FAST"),
                                  _rider(2, 6.0, surname="SLOW")])
    result = frame_builder.build_race_frames(sheet, circuit, fps=25)
    frames = result["frames"]

    # Start line: everyone begins at distance zero.
    first = frames[0]["drivers"]
    assert first["1"]["dist"] == pytest.approx(0.0, abs=1.0)
    assert first["2"]["dist"] == pytest.approx(0.0, abs=1.0)

    # Mid-race, the faster rider is ahead and classified first.
    mid = frames[len(frames) // 2]["drivers"]
    assert mid["1"]["progress"] > mid["2"]["progress"]
    assert mid["1"]["position"] == 1
    assert mid["2"]["position"] == 2

    # The fast rider completes two full laps.
    last_fast = frames[-1]["drivers"]["1"]
    assert last_fast["progress"] == pytest.approx(2.0, abs=0.05)


def test_position_sits_on_the_track_line():
    circuit = _square_circuit(length_m=400.0)
    sheet = AnalysisSheet(riders=[_rider(7, 5.0)])
    result = frame_builder.build_race_frames(sheet, circuit, fps=25)
    line = circuit.track_line
    for frame in (result["frames"][10], result["frames"][300]):
        car = frame["drivers"]["7"]
        expected = line.point_at(car["dist"] % circuit.length_m)
        assert car["x"] == pytest.approx(expected[0], abs=1.0)
        assert car["y"] == pytest.approx(expected[1], abs=1.0)
        assert car["speed"] > 0


def test_missing_sectors_fall_back_to_lap_time():
    circuit = _square_circuit()
    lap = Lap(number=1, lap_time_s=20.0, sectors=[None, None, None, None],
              speed_kmh=None)
    sheet = AnalysisSheet(riders=[RiderLaps(
        number=9, name="", surname="Y", constructor=None, nation=None,
        front_tyre=None, rear_tyre=None, laps=[lap])])
    result = frame_builder.build_race_frames(sheet, circuit, fps=25)
    # One 20s lap still yields a full replay ending at one lap done.
    assert result["frames"][-1]["drivers"]["9"]["progress"] == pytest.approx(1.0, abs=0.05)


@pytest.mark.slow
@pytest.mark.skipif(not os.path.exists(_ANALYSIS_PDF),
                    reason="Analysis PDF fixture absent; run download_pdfs.py")
def test_real_thailand_race_builds_and_marquez_wins():
    circuit = _square_circuit(length_m=4554.0)  # Buriram length; shape stubbed
    sheet = timing_pdf.parse_analysis(
        os.path.join(FIXTURES, "THA_2025_MotoGP_RAC_Analysis.pdf"))
    with open(os.path.join(FIXTURES, "classification_race.json")) as handle:
        classification = models.parse_classification(json.load(handle))

    result = frame_builder.build_race_frames(
        sheet, circuit, classification=classification, fps=10)
    frames = result["frames"]
    assert result["total_laps"] == 26
    # At the flag the winner leads on progress.
    final = frames[-1]["drivers"]
    leader = max(final.values(), key=lambda c: c["progress"])
    assert final["93"] is leader or final["93"]["position"] == 1


def test_tyre_compound_and_age_are_populated():
    circuit = _square_circuit(length_m=400.0)
    rider = _rider(1, 5.0, laps=3)
    rider.front_tyre = "Slick-Soft"
    rider.rear_tyre = "Slick-Medium"
    result = frame_builder.build_race_frames(
        AnalysisSheet(riders=[rider]), circuit, fps=25)
    frames = result["frames"]
    # Rear compound "Medium" maps to the tyre integer the tower colours by.
    from src.lib.tyres import get_tyre_compound_int
    assert frames[0]["drivers"]["1"]["tyre"] == get_tyre_compound_int("MEDIUM")
    # Tyre age climbs with the laps run on the one set.
    early = frames[len(frames) // 6]["drivers"]["1"]["tyre_life"]
    late = frames[-1]["drivers"]["1"]["tyre_life"]
    assert late > early
    assert late == pytest.approx(3, abs=1)
