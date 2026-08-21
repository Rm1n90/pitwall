"""Turning the official circuit SVG into a scaled centreline."""
import math
import os

import numpy as np
import pytest

from src.motogp import geometry

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")
VALENCIA = os.path.join(FIXTURES, "circuit_valencia.svg")
VALENCIA_LENGTH_M = 4005.0


@pytest.fixture(scope="module")
def circuit():
    return geometry.circuit_from_svg(VALENCIA, length_m=VALENCIA_LENGTH_M)


def test_flatten_path_produces_polyline():
    # A minimal path: a move then two lines then close.
    points = geometry.flatten_path("M0,0 L10,0 L10,10 Z")
    assert points[0] == (0.0, 0.0)
    assert (10.0, 0.0) in points
    assert (10.0, 10.0) in points


def test_relative_and_cubic_commands():
    # Relative horizontal move then a relative cubic; endpoints must land right.
    points = geometry.flatten_path("M10,10 h10 c0,10 10,10 20,20")
    assert points[0] == (10.0, 10.0)
    # After 'h10' the pen is at (20,10); the cubic ends at (20+20, 10+20).
    assert points[-1] == pytest.approx((40.0, 30.0))


def test_centreline_is_closed_and_scaled(circuit):
    xs = np.asarray(circuit.example_lap["X"], dtype=float)
    ys = np.asarray(circuit.example_lap["Y"], dtype=float)
    # The circuit is a loop: it returns near where it began.
    span = max(xs.max() - xs.min(), ys.max() - ys.min())
    gap = math.hypot(xs[0] - xs[-1], ys[0] - ys[-1])
    assert gap < 0.02 * span
    # Enough points to resolve corners.
    assert len(xs) > 200


def test_distance_matches_official_length(circuit):
    dist = np.asarray(circuit.example_lap["Distance"], dtype=float)
    # Arc length was scaled to the official lap length.
    assert dist[-1] == pytest.approx(VALENCIA_LENGTH_M, rel=0.01)
    assert circuit.length_m == pytest.approx(VALENCIA_LENGTH_M)
    # Distance is monotonic.
    assert np.all(np.diff(dist) >= 0)


def test_example_lap_has_render_columns(circuit):
    lap = circuit.example_lap
    for column in ("X", "Y", "Z", "Distance", "RelativeDistance", "DRS", "Speed"):
        assert column in lap
    # MotoGP has no DRS; the column exists but is all zero so the renderer's
    # DRS logic simply finds no zones.
    assert np.all(np.asarray(lap["DRS"]) == 0)


def test_track_line_available(circuit):
    from src.lib.track_geometry import TrackLine
    assert isinstance(circuit.track_line, TrackLine)
    # Length within a percent of official.
    assert circuit.track_line.length == pytest.approx(VALENCIA_LENGTH_M, rel=0.02)


def test_pit_lane_and_start_finish_extracted():
    import numpy as np
    from src.motogp import geometry
    svg = os.path.join(FIXTURES, "circuit_buriram.svg")
    circuit = geometry.circuit_from_svg(svg, 4554.0)
    # The pit lane is pulled from the second stroked path.
    assert circuit.pit_lane and len(circuit.pit_lane) > 5
    px = [p[0] for p in circuit.pit_lane]
    py = [p[1] for p in circuit.pit_lane]
    xs = np.asarray(circuit.example_lap["X"]); ys = np.asarray(circuit.example_lap["Y"])
    # Pit lane sits within the circuit's footprint, not floating off somewhere.
    assert xs.min() - 50 <= min(px) and max(px) <= xs.max() + 50
    assert ys.min() - 50 <= min(py) and max(py) <= ys.max() + 50
    # The centreline was rotated so index 0 sits at the detected start/finish,
    # which is where riders begin — near the pit lane, as on a real circuit.
    start = (xs[0], ys[0])
    pit_centre = (float(np.mean(px)), float(np.mean(py)))
    assert np.hypot(start[0] - pit_centre[0], start[1] - pit_centre[1]) < 0.4 * (xs.max() - xs.min())
