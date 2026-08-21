import json
import os
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def seasons_json():
    return load("seasons.json")


@pytest.fixture
def events_json():
    return load("events_2025.json")


@pytest.fixture
def categories_json():
    return load("categories_event.json")


@pytest.fixture
def sessions_json():
    return load("sessions.json")


@pytest.fixture
def classification_json():
    return load("classification_race.json")


@pytest.fixture
def riders_json():
    return load("riders_2025.json")


@pytest.fixture
def livetiming_json():
    return load("livetiming_lite.json")
