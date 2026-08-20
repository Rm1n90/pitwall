"""Tests for team radio clips."""

import pytest

from src.lib.team_radio import RadioClip, parse_captures, to_payload

PATH = "2026/2026-07-26_Race/"


def _payload(captures):
    return {"Captures": captures}


class TestParsing:
    def test_builds_a_full_clip_address(self):
        clips = parse_captures(_payload([
            {"Utc": "2026-07-26T12:53:19Z", "RacingNumber": "87",
             "Path": "TeamRadio/BEA_87.mp3"},
        ]), PATH, None)
        assert clips[0].url.endswith(f"{PATH}TeamRadio/BEA_87.mp3")
        assert clips[0].url.startswith("https://")

    def test_resolves_the_driver_code(self):
        clips = parse_captures(
            _payload([{"RacingNumber": "44", "Path": "a.mp3"}]),
            PATH, None, code_for_number=lambda n: {"44": "HAM"}[n])
        assert clips[0].code == "HAM"

    def test_falls_back_to_the_car_number(self):
        clips = parse_captures(
            _payload([{"RacingNumber": "44", "Path": "a.mp3"}]), PATH, None)
        assert clips[0].code == "44"

    def test_times_clips_against_the_replay_clock(self):
        clips = parse_captures(
            _payload([{"Utc": "x", "RacingNumber": "1", "Path": "a.mp3"}]),
            PATH, lambda utc: 132.6)
        assert clips[0].time_s == pytest.approx(132.6)

    def test_a_broken_timestamp_does_not_lose_the_clip(self):
        def _boom(_utc):
            raise ValueError("bad timestamp")

        clips = parse_captures(
            _payload([{"RacingNumber": "1", "Path": "a.mp3"}]), PATH, _boom)
        assert len(clips) == 1 and clips[0].time_s == 0.0

    def test_clips_come_back_in_order(self):
        times = iter([300.0, 100.0, 200.0])
        clips = parse_captures(
            _payload([{"Path": f"{i}.mp3"} for i in range(3)]),
            PATH, lambda _utc: next(times))
        assert [c.time_s for c in clips] == [100.0, 200.0, 300.0]

    def test_accepts_captures_keyed_by_index(self):
        clips = parse_captures(
            {"Captures": {"0": {"RacingNumber": "1", "Path": "a.mp3"}}},
            PATH, None)
        assert len(clips) == 1

    def test_skips_entries_without_a_path(self):
        clips = parse_captures(
            _payload([{"RacingNumber": "1"}, {"Path": "b.mp3"}]), PATH, None)
        assert len(clips) == 1

    @pytest.mark.parametrize("payload", [None, {}, {"Captures": None}, "nope"])
    def test_unusable_payloads_yield_nothing(self, payload):
        assert parse_captures(payload, PATH, None) == []


class TestPayload:
    def test_converts_for_the_stream(self):
        assert to_payload([RadioClip(1.5, "HAM", "http://x/a.mp3")]) == [
            {"time": 1.5, "code": "HAM", "url": "http://x/a.mp3"}]
