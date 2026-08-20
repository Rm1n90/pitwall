"""Tests for the cached circuit geometry used by live mode."""

import numpy as np
import pandas as pd
import pytest

from src.live import track_reference as tr


@pytest.fixture
def reference():
    angles = np.linspace(0, 2 * np.pi, 100)
    frame = pd.DataFrame({
        "X": 1000 * np.cos(angles),
        "Y": 1000 * np.sin(angles),
        "DRS": np.zeros(100),
        "Distance": np.linspace(0, 4000, 100),
    })
    return tr.TrackReference(frame, rotation=40.0, length_m=4000.0,
                             description="test lap")


class TestTrackReference:
    def test_reports_its_bounds(self, reference):
        x_min, x_max, y_min, y_max = reference.bounds()
        assert x_min == pytest.approx(-1000, abs=1)
        assert y_max == pytest.approx(1000, abs=1)


class TestPlainFrameConversion:
    def test_keeps_only_the_columns_the_replay_needs(self):
        # A FastF1 telemetry frame carries a reference to the whole session,
        # which would make the cached file enormous.
        frame = pd.DataFrame({
            "X": [1.0], "Y": [2.0], "Z": [3.0], "DRS": [0],
            "Distance": [10.0], "RelativeDistance": [0.1], "Speed": [100.0],
            "DriverAhead": ["44"], "Source": ["pos"], "Date": ["x"],
        })

        plain = tr._to_plain_frame(frame)

        assert set(plain.columns) == set(tr.REQUIRED_COLUMNS)
        assert type(plain) is pd.DataFrame

    def test_tolerates_missing_optional_columns(self):
        plain = tr._to_plain_frame(pd.DataFrame({"X": [1.0], "Y": [2.0]}))
        assert list(plain.columns) == ["X", "Y"]


class TestAlignmentCheck:
    def test_accepts_points_on_the_circuit(self, reference):
        assert tr.positions_look_aligned(reference, [(0, 1000), (1000, 0)])

    def test_rejects_points_from_a_different_coordinate_system(self, reference):
        assert not tr.positions_look_aligned(
            reference, [(500_000, 500_000), (600_000, 600_000)]
        )

    def test_accepts_an_empty_sample(self, reference):
        assert tr.positions_look_aligned(reference, [])

    def test_a_single_stray_car_does_not_fail_the_check(self, reference):
        points = [(0, 1000), (1000, 0), (-1000, 0), (900_000, 900_000)]
        assert tr.positions_look_aligned(reference, points)


class TestCaching:
    def test_round_trips_through_the_cache(self, reference, tmp_path):
        path = tr._cache_path(str(tmp_path), "Test Grand Prix 2026")
        tr._save_cached(path, reference)

        loaded = tr._load_cached(path)

        assert loaded is not None
        assert loaded.length_m == 4000.0
        assert loaded.rotation == 40.0
        assert "cached" in loaded.description
        assert len(loaded.example_lap) == len(reference.example_lap)

    def test_a_missing_cache_returns_nothing(self, tmp_path):
        assert tr._load_cached(str(tmp_path / "nope.pkl")) is None

    def test_a_corrupt_cache_is_ignored(self, tmp_path):
        path = tmp_path / "broken.pkl"
        path.write_bytes(b"not a pickle")
        assert tr._load_cached(str(path)) is None

    def test_cache_names_are_filesystem_safe(self, tmp_path):
        path = tr._cache_path(str(tmp_path), "São Paulo / Grand Prix 2026")
        assert "/" not in path.rsplit("/", 1)[-1]
