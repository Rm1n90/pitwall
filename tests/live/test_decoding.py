"""Tests for decoding the raw F1 live timing feeds."""

import base64
import json
import zlib

import pytest

from src.live import decoding


def _compress(payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    packed = compressor.compress(raw) + compressor.flush()
    return base64.b64encode(packed).decode("ascii")


class TestTimestamps:
    def test_parses_utc_with_seven_fractional_digits(self):
        parsed = decoding.parse_utc("2026-07-26T12:36:08.0619797Z")
        assert parsed.hour == 12 and parsed.minute == 36
        assert parsed.microsecond == 61979

    def test_parses_utc_without_fractional_digits(self):
        assert decoding.parse_utc("2026-07-26T12:36:08Z").second == 8

    @pytest.mark.parametrize("value", [None, "", "not a date", 42])
    def test_returns_none_for_unusable_input(self, value):
        assert decoding.parse_utc(value) is None

    def test_parses_session_stream_time(self):
        assert decoding.parse_stream_time("01:02:03.500").total_seconds() == \
            pytest.approx(3723.5)

    def test_parses_gmt_offset(self):
        assert decoding.parse_gmt_offset("02:00:00").total_seconds() == 7200

    def test_gmt_offset_defaults_to_zero(self):
        assert decoding.parse_gmt_offset(None).total_seconds() == 0


class TestLapTimes:
    @pytest.mark.parametrize("value,expected", [
        ("1:22.491", 82.491),
        ("29.105", 29.105),
        ("1:02:03.5", 3723.5),
    ])
    def test_parses_lap_time(self, value, expected):
        assert decoding.parse_lap_time(value) == pytest.approx(expected)

    @pytest.mark.parametrize("value", [None, "", "abc"])
    def test_returns_none_for_unusable_lap_time(self, value):
        assert decoding.parse_lap_time(value) is None


class TestStreamLines:
    def test_parses_a_compressed_position_line(self):
        payload = {"Position": [{"Timestamp": "2026-07-26T12:36:08.8Z",
                                 "Entries": {"1": {"Status": "OnTrack",
                                                   "X": 10, "Y": 20, "Z": 30}}}]}
        line = "00:26:59.457" + _compress(payload)

        message = decoding.parse_stream_line("Position.z", line)

        assert message.topic == "Position"
        assert message.stream_time == "00:26:59.457"
        assert message.data["Position"][0]["Entries"]["1"]["X"] == 10

    def test_parses_a_plain_json_line(self):
        line = '00:00:00.000{"Status":"2","Message":"Yellow"}'

        message = decoding.parse_stream_line("TrackStatus", line)

        assert message.topic == "TrackStatus"
        assert message.data == {"Status": "2", "Message": "Yellow"}

    def test_ignores_short_and_corrupt_lines(self):
        assert decoding.parse_stream_line("TrackStatus", "") is None
        assert decoding.parse_stream_line("Position.z", "00:00:00.000!!!") is None

    def test_splits_on_both_line_endings(self):
        assert decoding.split_feed_lines("a\r\nb\r\nc") == ["a", "b", "c"]
        assert decoding.split_feed_lines("a\nb") == ["a", "b"]

    def test_keeps_a_partial_trailing_line_for_the_next_poll(self):
        complete, partial = decoding.split_trailing_partial("one\r\ntwo\r\nthr")
        assert complete == "one\r\ntwo\r\n"
        assert partial == "thr"

    def test_treats_a_single_incomplete_line_as_partial(self):
        assert decoding.split_trailing_partial("half") == ("", "half")


class TestChannels:
    def test_converts_channels_to_named_values(self):
        values = decoding.channels_to_telemetry(
            {"0": 11000, "2": 315, "3": 8, "4": 100, "5": 0}
        )
        assert values["speed"] == 315
        assert values["gear"] == 8
        assert values["throttle"] == 100
        assert values["brake"] == 0.0

    def test_brake_is_boolean_shaped_like_the_replay_frames(self):
        assert decoding.channels_to_telemetry({"5": 100})["brake"] == 1.0
        assert decoding.channels_to_telemetry({"5": 0})["brake"] == 0.0

    def test_out_of_range_pedal_values_mean_no_data(self):
        # The feed publishes 104 when pedal data is not being transmitted.
        values = decoding.channels_to_telemetry({"4": 104, "5": 104})
        assert values["throttle"] is None
        assert values["brake"] is None

    def test_missing_drs_channel_is_off(self):
        # DRS is not part of the 2026 feed at all.
        assert decoding.channels_to_telemetry({"2": 300})["drs"] == 0


class TestMergePatch:
    def test_merges_nested_dictionaries(self):
        target = {"a": {"b": 1, "c": 2}}
        decoding.merge_patch(target, {"a": {"c": 3, "d": 4}})
        assert target == {"a": {"b": 1, "c": 3, "d": 4}}

    def test_applies_index_keyed_patches_to_lists(self):
        target = {"Sectors": [{"Segments": [{"Status": 2048}]}]}
        decoding.merge_patch(
            target, {"Sectors": {"0": {"Segments": {"1": {"Status": 2064}}}}}
        )
        assert target["Sectors"][0]["Segments"] == [
            {"Status": 2048}, {"Status": 2064}
        ]

    def test_replaces_scalars(self):
        target = {"Position": "1"}
        decoding.merge_patch(target, {"Position": "2"})
        assert target["Position"] == "2"

    def test_ignores_non_numeric_list_indices(self):
        target = {"items": [{"a": 1}]}
        decoding.merge_patch(target, {"items": {"bogus": {"a": 2}}})
        assert target["items"] == [{"a": 1}]
