"""Tests for the replay window's live-mode controller."""

import pytest

arcade = pytest.importorskip("arcade", reason="arcade is an optional dependency")

from src.interfaces.live_mode import LiveModeController  # noqa: E402


class _StubComponent:
    def __init__(self):
        self.session_info = {"total_laps": None}
        self.calls = []

    def set_race_data(self, **kwargs):
        self.calls.append(kwargs)


class _StubEngine:
    def __init__(self):
        self.statuses = [{"status": "1", "start_time": 0.0, "end_time": None}]
        self.laps = 70
        self.colors = {"NOR": (244, 118, 0)}
        self.state = type("S", (), {"race_control_messages": []})()

    def track_statuses(self):
        return self.statuses

    def total_laps(self):
        return self.laps

    def driver_colors(self):
        return self.colors

    def status_text(self):
        return "LIVE: static"


class _StubFrames(list):
    """A list that also exposes the live buffer's `latest` property."""

    @property
    def latest(self):
        return self[-1] if self else None


class _StubWindow:
    """Just enough of the replay window for the controller to drive."""

    def __init__(self, frame_count=100):
        self.frames = _StubFrames(
            [{"t": index * 0.04} for index in range(frame_count)]
        )
        self.has_weather = False
        self.frame_index = 0.0
        self.paused = False
        self.playback_speed = 1.0
        self.total_laps = None
        self.driver_colors = {}
        self.race_control_messages = []
        self.session_info_comp = _StubComponent()
        self.progress_bar_comp = _StubComponent()
        self.width = 1280
        self.height = 720


@pytest.fixture
def controller():
    return LiveModeController(_StubWindow(), _StubEngine())


class TestFollowingLive:
    def test_starts_following_the_live_edge(self, controller):
        assert controller.following is True

    def test_snaps_playback_to_the_newest_frame(self, controller):
        controller.on_update(0.04)
        assert controller.window.frame_index == pytest.approx(97.0)

    def test_reports_how_far_behind_the_viewer_is(self, controller):
        controller.window.frame_index = 47.0
        assert controller.frames_behind() == 52
        assert controller.seconds_behind() == pytest.approx(52 / 25)

    def test_does_nothing_while_the_buffer_is_still_empty(self):
        controller = LiveModeController(_StubWindow(frame_count=1),
                                        _StubEngine())
        controller.on_update(0.04)
        assert controller.window.frame_index == 0.0


class TestManualControl:
    def test_pausing_leaves_live(self, controller):
        controller.on_key_press(arcade.key.SPACE)
        assert controller.following is False

    def test_rewinding_leaves_live(self, controller):
        controller.on_key_press(arcade.key.LEFT)
        assert controller.following is False

    def test_playback_is_left_alone_once_the_viewer_takes_over(self, controller):
        controller.leave_live()
        controller.window.frame_index = 10.0
        controller.on_update(0.04)
        assert controller.window.frame_index == 10.0

    def test_g_jumps_back_to_live(self, controller):
        controller.leave_live()
        controller.window.paused = True
        controller.window.playback_speed = 4.0

        assert controller.on_key_press(arcade.key.G) is True
        assert controller.following is True
        assert controller.window.paused is False
        assert controller.window.playback_speed == 1.0
        assert controller.window.frame_index == 99.0

    def test_other_keys_are_not_consumed(self, controller):
        assert controller.on_key_press(arcade.key.D) is False


class TestMetadataRefresh:
    def test_picks_up_session_details_as_they_arrive(self, controller):
        controller.on_update(0.04)

        assert controller.window.total_laps == 70
        assert controller.window.session_info_comp.session_info[
            "total_laps"] == 70
        assert controller.window.driver_colors == {"NOR": (244, 118, 0)}
        assert controller.window.track_statuses == controller.engine.statuses
        assert controller.window.progress_bar_comp.calls

    def test_refresh_is_rate_limited(self, controller):
        controller.on_update(0.04)
        controller.on_update(0.04)
        assert len(controller.window.progress_bar_comp.calls) == 1

    def test_enables_the_weather_panel_once_weather_arrives(self, controller):
        # Weather is not in the feed until the session is under way, so the
        # panel has to switch on after the window was built.
        assert controller.window.has_weather is False
        controller.window.frames[-1]["weather"] = {"air_temp": 30.0}
        controller.on_update(0.04)

        assert controller.window.has_weather is True

    def test_a_failing_engine_does_not_break_playback(self, controller):
        def _boom():
            raise RuntimeError("feed gone")

        controller.engine.track_statuses = _boom
        controller._last_metadata_refresh = 0.0
        controller.on_update(0.04)  # must not raise
