"""The client wires URLs to parse functions; a fake getter keeps it offline."""
import json
import os

import pytest

from src.motogp.client import MotoGPClient

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def recording_client():
    """A client whose getter maps URL fragments to fixtures and records calls."""
    routes = {
        "results/seasons": "seasons.json",
        "results/events": "events_2025.json",
        "results/categories": "categories_event.json",
        "results/sessions": "sessions.json",
        "classification": "classification_race.json",
        "riders": "riders_2025.json",
        "livetiming-lite": "livetiming_lite.json",
    }
    calls = []

    def getter(url):
        calls.append(url)
        for fragment, fixture in routes.items():
            if fragment in url:
                return _load(fixture)
        raise AssertionError(f"no fixture for {url}")

    return MotoGPClient(getter=getter), calls


def test_seasons_and_events_flow(recording_client):
    client, calls = recording_client
    seasons = client.seasons()
    year = next(s for s in seasons if s.year == 2025)
    events = client.events(year.id, finished=True)
    assert any(e.short_name == "THA" for e in events)
    # The season UUID and the finished filter reach the URL.
    assert year.id in calls[-1]
    assert "isFinished=true" in calls[-1]


def test_sessions_and_classification(recording_client):
    client, _ = recording_client
    sessions = client.sessions("EVENT", "CATEGORY")
    race = next(s for s in sessions if s.code == "RAC")
    rows = client.classification(race.id)
    assert rows[0].rider_name == "Marc Marquez"


def test_live_timing(recording_client):
    client, _ = recording_client
    live = client.live_timing()
    assert live.num_laps == 7
    assert live.riders[0].pos == 1


def test_no_credentials_are_sent():
    """The client must never attach an auth header, cookie or token."""
    seen = {}

    def getter(url):
        seen["url"] = url
        return []

    MotoGPClient(getter=getter).seasons()
    assert "token" not in seen["url"].lower()
    assert "key" not in seen["url"].lower()
