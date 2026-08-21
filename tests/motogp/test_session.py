"""End-to-end session loading, driven entirely from recorded fixtures."""
import json
import os

import pytest

from src.motogp import session as msession
from src.motogp.client import MotoGPClient

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")
_ANALYSIS_PDF = os.path.join(FIXTURES, "THA_2025_MotoGP_RAC_Analysis.pdf")


def _fixture_getter(url):
    routes = {
        "results/seasons": "seasons.json",
        "results/events": "events_2025.json",
        "results/categories": "categories_event.json",
        "results/sessions": "sessions.json",
        "classification": "classification_race.json",
        "riders": "riders_2025.json",
        "seasonYear": "schedule_2025.json",  # broadcast /events?seasonYear=
    }
    # Order matters: classification and sessions both contain 'results/session'.
    if "classification" in url:
        name = "classification_race.json"
    elif "results/sessions" in url:
        name = "sessions.json"
    elif "results/events" in url:
        name = "events_2025.json"
    elif "results/categories" in url:
        name = "categories_event.json"
    elif "results/seasons" in url:
        name = "seasons.json"
    elif "riders" in url:
        name = "riders_2025.json"
    elif "seasonYear" in url:  # broadcast schedule
        name = "schedule_2025.json"
    else:
        raise AssertionError(f"no fixture route for {url}")
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_bytes(url):
    # The provider downloads the circuit SVG and the Analysis PDF; serve the
    # recorded copies from disk instead of the network.
    if url.endswith(".svg"):
        path = os.path.join(FIXTURES, "circuit_buriram.svg")
    elif url.endswith(".pdf"):
        path = os.path.join(FIXTURES, "THA_2025_MotoGP_RAC_Analysis.pdf")
    else:
        raise AssertionError(f"unexpected download {url}")
    with open(path, "rb") as handle:
        return handle.read()


@pytest.mark.skipif(not os.path.exists(_ANALYSIS_PDF),
                    reason="Analysis PDF fixture absent; run download_pdfs.py")
def test_load_thailand_race_end_to_end(tmp_path):
    client = MotoGPClient(getter=_fixture_getter)
    replay = msession.load_race(
        2025, "THA", "MotoGP", "RAC", client=client,
        cache_dir=str(tmp_path), fetch_bytes=_fetch_bytes, fps=5)

    assert replay.total_laps == 26
    assert "THAILAND" in replay.title.upper()
    assert replay.session_type == "R"
    assert len(replay.drivers) >= 20
    # The example lap is a full circuit for the renderer.
    assert len(replay.example_lap["X"]) > 200
    # Winner leads on progress at the flag.
    final = replay.frames[-1]["drivers"]
    assert final["93"]["position"] == 1
    # Colours are present for every rider on track.
    assert all(code in replay.driver_colors for code in replay.drivers)
    # The PDF and SVG were cached to disk.
    assert (tmp_path / "analysis").exists()
    assert (tmp_path / "circuits").exists()
