"""Tests for the accumulated live session state."""

from datetime import datetime, timezone

import pytest

from src.live.decoding import LiveMessage
from src.live.state import DriverSamples, LiveSessionState


def _utc(second: float) -> str:
    base = datetime(2026, 7, 26, 13, 0, 0, tzinfo=timezone.utc)
    return (base.replace(microsecond=0)
            + __import__("datetime").timedelta(seconds=second)
            ).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _position_message(second: float, entries: dict,
                      stream_time: str = "00:10:00.000") -> LiveMessage:
    return LiveMessage(
        "Position",
        {"Position": [{"Timestamp": _utc(second), "Entries": entries}]},
        stream_time,
    )


class TestDriverSamples:
    def test_interpolates_between_two_samples(self):
        samples = DriverSamples()
        samples.add_position(0.0, 0.0, 0.0, True)
        samples.add_position(1.0, 100.0, 200.0, True)

        x, y, on_track = samples.position_at(0.25)

        assert x == pytest.approx(25.0)
        assert y == pytest.approx(50.0)
        assert on_track is True

    def test_clamps_outside_the_sample_range(self):
        samples = DriverSamples()
        # The two samples must be far enough apart to count as real movement;
        # a repeated coordinate is deliberately not stored.
        samples.add_position(1.0, 500.0, 600.0, True)
        samples.add_position(2.0, 700.0, 800.0, True)

        assert samples.position_at(0.0)[:2] == (500.0, 600.0)
        assert samples.position_at(9.0)[:2] == (700.0, 800.0)

    def test_returns_none_without_any_sample(self):
        assert DriverSamples().position_at(1.0) is None

    def test_drops_samples_that_arrive_too_close_together(self):
        samples = DriverSamples()
        samples.add_position(0.0, 0.0, 0.0, True)
        samples.add_position(0.01, 500.0, 500.0, True)

        assert len(samples.times) == 1

    def test_rejects_a_single_sample_glitch(self):
        samples = DriverSamples()
        samples.add_position(0.0, 0.0, 0.0, True)
        samples.add_position(0.25, 100.0, 0.0, True)
        # ~900 m away in a quarter of a second is not possible.
        samples.add_position(0.5, 9000.0, 9000.0, True)
        samples.add_position(0.75, 200.0, 0.0, True)

        assert list(samples.xs) == [0.0, 100.0, 200.0]
        assert samples.rejected_count == 1

    def test_accepts_a_relocation_once_readings_agree(self):
        samples = DriverSamples()
        samples.add_position(0.0, 0.0, 0.0, True)
        # A genuine reposition: distant, but consistent from sample to sample.
        samples.add_position(0.25, 9000.0, 9000.0, True)
        samples.add_position(0.50, 9010.0, 9005.0, True)
        samples.add_position(0.75, 9020.0, 9010.0, True)

        assert samples.xs[-1] == 9020.0

    def test_a_long_gap_makes_a_big_jump_plausible(self):
        samples = DriverSamples()
        samples.add_position(0.0, 0.0, 0.0, True)
        samples.add_position(60.0, 90000.0, 90000.0, True)

        assert len(samples.times) == 2

    def test_carries_pedal_values_forward_when_they_drop_out(self):
        samples = DriverSamples()
        samples.add_car(0.0, {"throttle": 100.0, "brake": 0.0})
        samples.add_car(1.0, {"throttle": None, "brake": None})

        assert samples.car_at(1.0)["throttle"] == 100.0
        assert samples.car_at(1.0)["brake"] == 0.0

    def test_defaults_pedals_to_zero_when_never_reported(self):
        samples = DriverSamples()
        samples.add_car(0.0, {"throttle": None, "brake": None})

        assert samples.car_at(0.0)["throttle"] == 0.0

    def test_returns_the_most_recent_telemetry_at_or_before_a_time(self):
        samples = DriverSamples()
        samples.add_car(0.0, {"speed": 100.0})
        samples.add_car(1.0, {"speed": 200.0})

        assert samples.car_at(0.9)["speed"] == 100.0
        assert samples.car_at(1.5)["speed"] == 200.0


class TestSessionState:
    def test_session_info_sets_frame_time_zero(self):
        state = LiveSessionState()
        state.apply(LiveMessage("SessionInfo", {
            "StartDate": "2026-07-26T15:00:00", "GmtOffset": "02:00:00",
        }))
        assert state.t0 == datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)

    def test_driver_list_provides_codes_and_colours(self):
        state = LiveSessionState()
        state.apply(LiveMessage("DriverList", {
            "1": {"Tla": "NOR", "TeamColour": "F47600"},
        }))

        assert state.driver_code("1") == "NOR"
        assert state.driver_colors() == {"NOR": (244, 118, 0)}

    def test_unknown_driver_falls_back_to_the_car_number(self):
        assert LiveSessionState().driver_code("77") == "#77"

    def test_ignores_malformed_team_colours(self):
        state = LiveSessionState()
        state.apply(LiveMessage("DriverList", {"1": {"Tla": "NOR",
                                                     "TeamColour": "zz"}}))
        assert state.driver_colors() == {}

    def test_timing_updates_are_merged_not_replaced(self):
        state = LiveSessionState()
        state.apply(LiveMessage("TimingData",
                                {"Lines": {"1": {"Position": "1",
                                                 "NumberOfLaps": 3}}}))
        state.apply(LiveMessage("TimingData",
                                {"Lines": {"1": {"NumberOfLaps": 4}}}))

        assert state.timing["1"] == {"Position": "1", "NumberOfLaps": 4}

    def test_current_stint_is_the_latest_one(self):
        state = LiveSessionState()
        state.apply(LiveMessage("TimingAppData", {"Lines": {"1": {"Stints": [
            {"Compound": "MEDIUM", "TotalLaps": 17},
            {"Compound": "HARD", "TotalLaps": 4},
        ]}}}))

        assert state.current_stint("1")["Compound"] == "HARD"

    def test_stints_delivered_as_an_index_keyed_dict(self):
        state = LiveSessionState()
        state.apply(LiveMessage("TimingAppData", {"Lines": {"1": {"Stints": {
            "0": {"Compound": "SOFT", "TotalLaps": 2},
        }}}}))

        assert state.current_stint("1")["Compound"] == "SOFT"

    def test_lap_count_exposes_current_and_total(self):
        state = LiveSessionState()
        state.apply(LiveMessage("LapCount", {"CurrentLap": 12, "TotalLaps": 70}))

        assert state.current_lap() == 12
        assert state.total_laps() == 70

    def test_lap_count_defaults_are_safe(self):
        state = LiveSessionState()
        assert state.current_lap() == 1
        assert state.total_laps() is None

    def test_position_samples_are_stored_per_driver(self):
        state = LiveSessionState()
        state.set_session_start(datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc))
        state.apply(_position_message(10, {"1": {"Status": "OnTrack",
                                                 "X": 100, "Y": 200, "Z": 0}}))

        assert state.has_position_data()
        assert state.samples["1"].position_at(10.0)[:2] == (100.0, 200.0)
        assert state.latest_sample_t == pytest.approx(10.0)

    def test_position_entries_without_coordinates_are_skipped(self):
        state = LiveSessionState()
        state.set_session_start(datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc))
        state.apply(_position_message(10, {"1": {"Status": "OnTrack"}}))

        assert not state.has_position_data()

    def test_track_status_history_is_resolved_against_the_stream_clock(self):
        state = LiveSessionState()
        state.set_session_start(datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc))
        # A position sample teaches the state how stream time maps onto UTC.
        state.apply(_position_message(600, {"1": {"X": 0, "Y": 0}},
                                      stream_time="01:00:00.000"))
        state.apply(LiveMessage("TrackStatus", {"Status": "4",
                                                "Message": "SCDeployed"},
                                "01:00:10.000"))
        state.apply(LiveMessage("TrackStatus", {"Status": "1",
                                                "Message": "AllClear"},
                                "01:01:10.000"))

        history = state.resolved_track_status_history()
        assert [entry["status"] for entry in history] == ["4", "1"]
        assert history[0]["start_time"] == pytest.approx(610.0)
        assert history[0]["end_time"] == pytest.approx(670.0)
        assert history[1]["end_time"] is None

    def test_repeated_track_status_is_not_recorded_twice(self):
        state = LiveSessionState()
        state.apply(LiveMessage("TrackStatus", {"Status": "2"}, "00:00:01.000"))
        state.apply(LiveMessage("TrackStatus", {"Status": "2"}, "00:00:02.000"))

        assert len(state.track_status_history) == 1

    def test_race_control_messages_are_deduplicated(self):
        state = LiveSessionState()
        state.set_session_start(datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc))
        payload = {"Messages": [{"Utc": _utc(30), "Message": "YELLOW",
                                 "Category": "Flag", "Flag": "YELLOW"}]}
        state.apply(LiveMessage("RaceControlMessages", payload))
        state.apply(LiveMessage("RaceControlMessages", payload))

        assert len(state.race_control_messages) == 1
        assert state.race_control_messages[0]["time"] == pytest.approx(30.0)

    def test_unknown_topics_are_ignored(self):
        state = LiveSessionState()
        state.apply(LiveMessage("SomethingNew", {"a": 1}))
        assert state.snapshot_meta()["session_info"] == {}


class TestExtrapolatedClock:
    """F1 publishes the clock when it starts or stops, not every second, so a
    client has to continue the countdown itself."""

    def _state(self, remaining="01:00:00", extrapolating=True, issued=30.0):
        state = LiveSessionState()
        state.set_session_start(datetime(2026, 7, 26, 13, 0,
                                         tzinfo=timezone.utc))
        state.apply(LiveMessage("ExtrapolatedClock", {
            "Utc": _utc(issued),
            "Remaining": remaining,
            "Extrapolating": extrapolating,
        }))
        return state

    def test_reads_the_published_value(self):
        assert self._state().time_remaining_s() == pytest.approx(3600.0)

    def test_counts_down_from_when_it_was_published(self):
        # Published at t=30 with an hour left, so at t=630 there are 50
        # minutes left, not an hour.
        state = self._state(issued=30.0)
        assert state.time_remaining_s(630.0) == pytest.approx(3000.0)

    def test_a_held_clock_does_not_count_down(self):
        # Under a red flag the clock stops and the value stands as published.
        state = self._state(extrapolating=False)
        assert state.time_remaining_s(630.0) == pytest.approx(3600.0)

    def test_never_goes_negative(self):
        state = self._state(remaining="00:00:10")
        assert state.time_remaining_s(99999.0) == 0.0

    def test_is_unknown_without_a_clock(self):
        assert LiveSessionState().time_remaining_s(100.0) is None


class TestPitStopsInState:
    def test_records_published_stop_times(self):
        state = LiveSessionState()
        state.apply(LiveMessage("DriverList", {"44": {"Tla": "HAM"}}))
        state.apply(LiveMessage("PitStopSeries", {"PitTimes": {"44": [
            {"PitStop": {"PitStopTime": "2.6", "PitLaneTime": "21.7",
                         "Lap": "13"}},
        ]}}))

        by_code = state.pit_stops_by_code()
        assert by_code["HAM"][0].stationary_s == 2.6

    def test_a_resent_series_replaces_rather_than_duplicates(self):
        state = LiveSessionState()
        payload = {"PitTimes": {"1": [
            {"PitStop": {"PitStopTime": "2.3", "Lap": "20"}}]}}
        state.apply(LiveMessage("PitStopSeries", payload))
        state.apply(LiveMessage("PitStopSeries", payload))

        assert len(state.pit_stops["1"]) == 1


def _timing_message(lines: dict, stream_time: str = "00:10:00.000") -> LiveMessage:
    return LiveMessage("TimingData", {"Lines": lines}, stream_time)


class TestLapTimesFromTheFeed:
    """The feed says outright which times are personal or overall bests.

    Nothing has to be inferred from the sector status codes, which is worth
    relying on: the codes are undocumented.
    """

    def test_reads_the_last_lap_time(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"LastLapTime": {"Value": "1:22.491"}}}))

        assert state.last_lap_time("1") == pytest.approx(82.491)

    def test_reads_the_best_lap_time(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"BestLapTime": {"Value": "1:20.100"}}}))

        assert state.best_lap_time("1") == pytest.approx(80.1)

    def test_a_driver_with_no_lap_yet_has_no_times(self):
        state = LiveSessionState()
        assert state.last_lap_time("1") is None
        assert state.best_lap_time("1") is None

    def test_an_empty_time_reads_as_no_time(self):
        # Before a driver sets a lap the feed sends an empty string.
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"BestLapTime": {"Value": ""}}}))

        assert state.best_lap_time("1") is None

    def test_a_later_message_replaces_the_earlier_one(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"LastLapTime": {"Value": "1:22.491"}}}))
        state.apply(_timing_message({"1": {"LastLapTime": {"Value": "1:21.004"}}}))

        assert state.last_lap_time("1") == pytest.approx(81.004)


class TestSectorStatusFromTheFeed:

    def test_a_normal_sector_reads_as_normal(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"Sectors": [
            {"Value": "28.1", "OverallFastest": False, "PersonalFastest": False},
        ]}}))

        assert state.sector_status("1")[0] == 0

    def test_a_personal_best_sector_is_marked(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"Sectors": [
            {"Value": "28.1", "OverallFastest": False, "PersonalFastest": True},
        ]}}))

        assert state.sector_status("1")[0] == 1

    def test_an_overall_best_sector_is_marked(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"Sectors": [
            {"Value": "27.9", "OverallFastest": True, "PersonalFastest": True},
        ]}}))

        assert state.sector_status("1")[0] == 2

    def test_all_three_sectors_come_back(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"Sectors": [
            {"Value": "28.1", "PersonalFastest": True},
            {"Value": "31.0"},
            {"Value": "23.4", "OverallFastest": True},
        ]}}))

        assert state.sector_status("1") == [1, 0, 2]

    def test_a_driver_with_no_sectors_reads_as_normal(self):
        state = LiveSessionState()
        assert state.sector_status("1") == [0, 0, 0]

    def test_sectors_arriving_as_a_partial_update_are_merged(self):
        # Updates address individual sectors by index rather than resending
        # the whole array.
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"Sectors": [
            {"Value": "28.1"}, {"Value": ""}, {"Value": ""},
        ]}}))
        state.apply(_timing_message({"1": {"Sectors": {
            "1": {"Value": "31.0", "OverallFastest": True},
        }}}))

        assert state.sector_status("1") == [0, 2, 0]


class TestLapsCompleted:

    def test_reads_the_lap_count(self):
        state = LiveSessionState()
        state.apply(_timing_message({"1": {"NumberOfLaps": 14}}))

        assert state.laps_completed("1") == 14

    def test_a_driver_who_has_not_run_has_none(self):
        state = LiveSessionState()
        assert state.laps_completed("1") is None
