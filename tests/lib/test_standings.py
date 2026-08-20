"""Tests for championship standings."""

import pytest

from src.lib.standings import (
    parse_constructor_standings,
    parse_driver_standings,
    parse_prediction,
)


def _driver_payload(rows):
    return {"MRData": {"StandingsTable": {"StandingsLists": [
        {"DriverStandings": rows}]}}}


class TestDriverStandings:
    def test_reads_a_row(self):
        standings = parse_driver_standings(_driver_payload([{
            "position": "1", "points": "423", "wins": "7",
            "Driver": {"code": "NOR", "givenName": "Lando",
                       "familyName": "Norris"},
            "Constructors": [{"name": "McLaren"}],
        }]))
        entry = standings[0]
        assert (entry.position, entry.name, entry.points, entry.wins) == \
            (1, "NOR", 423.0, 7)
        assert entry.full_name == "Lando Norris"
        assert entry.team == "McLaren"

    def test_a_driver_without_a_code_falls_back_to_the_id(self):
        standings = parse_driver_standings(_driver_payload([{
            "position": "5", "points": "10",
            "Driver": {"driverId": "someone"}, "Constructors": [{}],
        }]))
        assert standings[0].name == "someone"

    @pytest.mark.parametrize("payload", [
        {}, {"MRData": {}}, {"MRData": {"StandingsTable":
                                        {"StandingsLists": []}}}, None,
    ])
    def test_unusable_payloads_yield_nothing(self, payload):
        assert parse_driver_standings(payload) == []


class TestConstructorStandings:
    def test_reads_a_row(self):
        standings = parse_constructor_standings({"MRData": {"StandingsTable": {
            "StandingsLists": [{"ConstructorStandings": [
                {"position": "1", "points": "833", "wins": "12",
                 "Constructor": {"name": "McLaren"}}]}]}}})
        assert (standings[0].name, standings[0].points) == ("McLaren", 833.0)


class TestPrediction:
    def test_reads_drivers_and_teams(self):
        parsed = parse_prediction({
            "Drivers": {"12": {"RacingNumber": "12", "CurrentPosition": 1,
                               "PredictedPosition": 2}},
            "Teams": {"Mercedes": {"CurrentPosition": 1,
                                   "PredictedPosition": 1}},
        })
        assert parsed["drivers"]["12"]["predicted_position"] == 2
        assert parsed["teams"]["Mercedes"]["current_position"] == 1

    @pytest.mark.parametrize("payload", [None, {}, "nope", {"Drivers": []}])
    def test_unusable_payloads_yield_empty_sections(self, payload):
        parsed = parse_prediction(payload)
        assert parsed == {"drivers": {}, "teams": {}}
