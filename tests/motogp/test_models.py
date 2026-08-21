"""Parsing pulselive JSON into typed models."""
from src.motogp import models


def test_seasons_parse_year_and_current(seasons_json):
    seasons = models.parse_seasons(seasons_json)
    assert seasons[0].year == 2026
    assert seasons[0].current is True
    # Every season carries a UUID.
    assert all(s.id for s in seasons)
    # 2025 is present and not current.
    y2025 = next(s for s in seasons if s.year == 2025)
    assert y2025.current is False


def test_events_carry_circuit_and_short_name(events_json):
    events = models.parse_events(events_json)
    tha = next(e for e in events if e.short_name == "THA")
    assert "THAILAND" in tha.name.upper()
    assert tha.circuit.name == "Chang International Circuit"
    assert tha.circuit.place == "Buriram"
    assert tha.country_iso == "TH"


def test_categories_names_are_normalised(categories_json):
    cats = models.parse_categories(categories_json)
    names = {c.name for c in cats}
    # The trademark glyph is stripped so callers can match on plain names.
    assert "MotoGP" in names
    assert "Moto2" in names
    assert "Moto3" in names
    assert all("™" not in c.name for c in cats)


def test_sessions_build_codes_and_expose_files(sessions_json):
    sessions = models.parse_sessions(sessions_json)
    codes = [s.code for s in sessions]
    # FP number is folded into the code; single sessions keep their type.
    assert "FP1" in codes and "FP2" in codes
    assert "Q1" in codes and "Q2" in codes
    assert "RAC" in codes and "SPR" in codes and "WUP" in codes
    race = next(s for s in sessions if s.code == "RAC")
    assert race.analysis_url.endswith("/MotoGP/RAC/Analysis.pdf")
    assert race.lap_chart_url.endswith("/MotoGP/RAC/LapChart.pdf")
    assert race.condition["track"] == "Dry"


def test_classification_rows_ordered_with_gaps(classification_json):
    rows = models.parse_classification(classification_json)
    assert rows[0].position == 1
    assert rows[0].rider_name == "Marc Marquez"
    assert rows[0].rider_number == 93
    assert rows[0].gap_first == 0.0
    assert rows[0].total_laps == 26
    assert rows[0].points == 25
    # Classified riders lead, sorted by finishing position; the two retirees
    # (position None) come last.
    classified = [r.position for r in rows if r.position is not None]
    assert classified == sorted(classified)
    assert [r.position for r in rows[-2:]] == [None, None]


def test_riders_expose_number_colour_and_portrait(riders_json):
    riders = models.parse_riders(riders_json)
    marc = next(r for r in riders if r.legacy_id == 7444)
    assert marc.surname.upper() == "MARQUEZ"
    assert marc.number == 93
    assert marc.color.startswith("#")
    assert marc.portrait_url and marc.portrait_url.startswith("http")


def test_livetiming_parses_head_and_riders(livetiming_json):
    live = models.parse_livetiming(livetiming_json)
    assert live.num_laps == 7
    assert live.riders[0].pos == 1
    assert live.riders[0].surname == "MCDONALD"
    # Classified riders come back ordered by track position; DNS entries last.
    classified = [r.pos for r in live.riders if r.pos > 0]
    assert classified == sorted(classified)
    assert live.riders[0].pos == 1
    # Gaps are parsed to seconds; the leader is level with itself.
    assert live.riders[0].gap_first == 0.0
    assert live.riders[0].color.startswith("#")
