"""Tests for live session discovery."""

from datetime import datetime, timezone

import pytest

from src.live import schedule


def _ref(**overrides):
    defaults = dict(
        year=2026, key=11342,
        path="2026/2026-07-26_Hungarian_Grand_Prix/2026-07-26_Race/",
        session_type="Race", name="Race", meeting_name="Hungarian Grand Prix",
        country="Hungary", location="Budapest",
        circuit_short_name="Hungaroring",
        start_utc=datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 26, 15, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return schedule.LiveSessionRef(**defaults)


class TestSessionRef:
    def test_title_combines_meeting_and_session(self):
        assert _ref().title == "Hungarian Grand Prix - Race"

    def test_is_live_during_the_session(self):
        assert _ref().is_live(datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc))

    def test_is_live_shortly_before_the_start(self):
        assert _ref().is_live(datetime(2026, 7, 26, 12, 30, tzinfo=timezone.utc))

    def test_is_not_live_long_before_the_start(self):
        assert not _ref().is_live(
            datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc))

    def test_stays_live_after_the_scheduled_end_for_overruns(self):
        assert _ref().is_live(datetime(2026, 7, 26, 17, 0, tzinfo=timezone.utc))

    def test_is_not_live_the_next_day(self):
        assert not _ref().is_live(
            datetime(2026, 7, 27, 13, 0, tzinfo=timezone.utc))

    def test_counts_down_to_the_start(self):
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
        assert _ref().seconds_until_start(now) == 3600

    @pytest.mark.parametrize("name,session_type,expected", [
        ("Race", "Race", "R"),
        ("Qualifying", "Qualifying", "Q"),
        ("Sprint", "Race", "S"),
        ("Sprint Qualifying", "Qualifying", "SQ"),
        ("Practice 2", "Practice", "FP2"),
        ("Practice", "Practice", "FP1"),
    ])
    def test_maps_onto_fastf1_session_codes(self, name, session_type, expected):
        assert _ref(name=name,
                    session_type=session_type).fastf1_session_type() == expected


class TestSessionPaths:
    def test_builds_the_path_f1_publishes(self):
        # Verified against F1's own index for this session.
        path = schedule.build_session_path(
            datetime(2026, 7, 26), "Hungarian Grand Prix",
            datetime(2026, 7, 25), "Qualifying",
        )
        assert path == \
            "2026/2026-07-26_Hungarian_Grand_Prix/2026-07-25_Qualifying/"

    def test_replaces_spaces_in_names(self):
        path = schedule.build_session_path(
            datetime(2026, 8, 23), "Dutch Grand Prix",
            datetime(2026, 8, 21), "Practice 1",
        )
        assert path == "2026/2026-08-23_Dutch_Grand_Prix/2026-08-21_Practice_1/"


class TestIndexParsing:
    def test_converts_local_start_times_to_utc(self):
        meeting = {"Name": "Hungarian Grand Prix", "Location": "Budapest",
                   "Country": {"Name": "Hungary"},
                   "Circuit": {"ShortName": "Hungaroring"}}
        entry = {"Key": 11342, "Type": "Race", "Name": "Race",
                 "StartDate": "2026-07-26T15:00:00",
                 "EndDate": "2026-07-26T17:00:00",
                 "GmtOffset": "02:00:00",
                 "Path": "2026/x/y/"}

        parsed = schedule._session_from_entry(2026, meeting, entry)

        assert parsed.start_utc == datetime(2026, 7, 26, 13, 0,
                                            tzinfo=timezone.utc)
        assert parsed.end_utc == datetime(2026, 7, 26, 15, 0,
                                          tzinfo=timezone.utc)
        assert parsed.circuit_short_name == "Hungaroring"

    def test_skips_entries_without_a_path_or_start(self):
        assert schedule._session_from_entry(2026, {}, {"Name": "Race"}) is None


class TestDescribeWait:
    @pytest.mark.parametrize("seconds,expected", [
        (0, "0s"),
        (45, "45s"),
        (150, "2m 30s"),
        (7200, "2h 00m"),
        (-10, "0s"),
    ])
    def test_formats_a_countdown(self, seconds, expected):
        assert schedule.describe_wait(seconds) == expected


class TestResolveLiveSession:
    def test_prefers_the_most_recently_started_overlapping_session(self,
                                                                   monkeypatch):
        early = _ref(name="Sprint",
                     start_utc=datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
                     end_utc=datetime(2026, 7, 26, 11, 0, tzinfo=timezone.utc))
        late = _ref(name="Race")
        monkeypatch.setattr(schedule, "fetch_season_sessions",
                            lambda *a, **k: [early, late])

        found = schedule.find_live_session(
            now=datetime(2026, 7, 26, 13, 30, tzinfo=timezone.utc))
        assert found.name == "Race"

    def test_returns_none_when_nothing_is_live(self, monkeypatch):
        monkeypatch.setattr(schedule, "fetch_season_sessions",
                            lambda *a, **k: [_ref()])
        assert schedule.find_live_session(
            now=datetime(2026, 1, 1, tzinfo=timezone.utc)) is None

    def test_falls_back_to_the_calendar_when_the_index_lags(self, monkeypatch):
        # F1 only indexes a weekend once it is under way, so an upcoming
        # session has to come from the published schedule instead.
        monkeypatch.setattr(schedule, "find_live_session",
                            lambda **kwargs: None)
        monkeypatch.setattr(schedule, "find_scheduled_session",
                            lambda **kwargs: _ref(name="Practice 1"))

        assert schedule.resolve_live_session().name == "Practice 1"

    def test_survives_an_unreachable_index(self, monkeypatch):
        def _boom(**kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(schedule, "find_live_session", _boom)
        monkeypatch.setattr(schedule, "find_scheduled_session",
                            lambda **kwargs: None)

        assert schedule.resolve_live_session() is None
