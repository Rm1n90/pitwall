"""Tests for live mode configuration."""

import pytest

from src.live.config import (
    DEFAULT_SIGNALR_DELAY_S,
    DEFAULT_STATIC_DELAY_S,
    LIVE_FPS,
    SOURCE_SIGNALR,
    SOURCE_STATIC,
    LiveConfig,
)


class TestLiveConfig:
    def test_defaults_to_the_automatic_source(self):
        assert LiveConfig().source == "auto"

    def test_rejects_an_unknown_source(self):
        with pytest.raises(ValueError, match="Unknown live source"):
            LiveConfig(source="carrier-pigeon")

    def test_the_static_feed_gets_a_longer_default_delay(self):
        assert LiveConfig(source=SOURCE_STATIC).delay_s == DEFAULT_STATIC_DELAY_S
        assert LiveConfig(source=SOURCE_SIGNALR).delay_s == \
            DEFAULT_SIGNALR_DELAY_S

    def test_an_explicit_delay_wins(self):
        assert LiveConfig(delay_s=0.5).delay_s == 0.5

    def test_a_negative_delay_is_clamped(self):
        assert LiveConfig(delay_s=-5).delay_s == 0.0

    def test_the_poll_interval_has_a_floor(self):
        assert LiveConfig(poll_interval_s=0.01).poll_interval_s == 0.5

    def test_the_frame_budget_covers_at_least_a_minute(self):
        assert LiveConfig(max_frames=1).max_frames == LIVE_FPS * 60

    def test_the_delay_can_be_set_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("F1_LIVE_DELAY", "4.5")
        assert LiveConfig().delay_s == 4.5

    def test_an_invalid_environment_delay_is_ignored(self, monkeypatch):
        monkeypatch.setenv("F1_LIVE_DELAY", "soon")
        assert LiveConfig().delay_s == DEFAULT_SIGNALR_DELAY_S

    def test_anonymous_mode_can_be_set_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("F1_LIVE_NO_AUTH", "true")
        assert LiveConfig().no_auth is True

    def test_car_topics_are_subscribed_to_by_default(self):
        assert "Position.z" in LiveConfig().topics
        assert "CarData.z" in LiveConfig().topics
