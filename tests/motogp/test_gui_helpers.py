"""Qt-free MotoGP selector helpers."""
import json
import os

from src.motogp import gui_helpers, models

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "motogp")


def test_event_rows_shape_and_drop_tests():
    with open(os.path.join(FIXTURES, "events_2025.json")) as handle:
        events = models.parse_events(json.load(handle))
    rows = gui_helpers.motogp_event_rows(events)
    # Rows carry the keys the schedule tree reads, plus MotoGP identity.
    tha = next(r for r in rows if r["short_name"] == "THA")
    assert tha["series"] == "motogp"
    assert "THAILAND" in tha["event_name"].upper()
    assert tha["country"] == "TH"
    assert tha["circuit_name"] == "Chang International Circuit"
    assert isinstance(tha["round_number"], int)
    # Every row carries the series marker.
    assert all("series" in r for r in rows)


def test_build_command_has_all_flags():
    cmd = gui_helpers.build_motogp_command(
        "python", "/x/main.py", 2025, "THA", "MotoGP", "RAC")
    assert cmd[:3] == ["python", "/x/main.py", "--motogp"]
    assert cmd[cmd.index("--year") + 1] == "2025"
    assert cmd[cmd.index("--event") + 1] == "THA"
    assert cmd[cmd.index("--class") + 1] == "MotoGP"
    assert cmd[cmd.index("--session") + 1] == "RAC"
    assert "--verbose" not in cmd


def test_build_command_verbose():
    cmd = gui_helpers.build_motogp_command(
        "python", "/x/main.py", 2025, "THA", "MotoGP", "SPR", verbose=True)
    assert "--verbose" in cmd


def test_session_buttons_cover_the_three_classes():
    categories = {c for _, c, _ in gui_helpers.MOTOGP_SESSION_BUTTONS}
    assert {"MotoGP", "Moto2", "Moto3"} <= categories
    # A sprint is offered for the premier class.
    assert ("MotoGP Sprint", "MotoGP", "SPR") in gui_helpers.MOTOGP_SESSION_BUTTONS
