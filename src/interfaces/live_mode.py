"""Live-session behaviour for the replay window.

The replay window is built around a fixed array of frames. Live mode keeps
that model and simply lets the array grow: this controller follows the newest
frame, refreshes the session metadata that only becomes known as the session
runs, and lets the viewer rewind into what has already been received and jump
back to live again.

Keeping the logic here means the replay window itself only needs a handful of
hooks rather than being threaded through with live-specific branches.
"""

import time

import arcade

# How many frames behind the newest one to sit while following live. One
# frame of slack absorbs the race between the producer and the renderer.
LIVE_FOLLOW_LAG_FRAMES = 2

# Session metadata (total laps, colours, track status) is refreshed on this
# interval rather than every frame.
METADATA_REFRESH_S = 2.0

# Colours for the live badge.
BADGE_LIVE_COLOR = (220, 40, 40)
BADGE_BEHIND_COLOR = (200, 140, 30)
BADGE_TEXT_COLOR = (255, 255, 255)


class LiveModeController:
    """Drives a replay window from a running :class:`LiveRaceEngine`.

    Args:
        window: The replay window to drive.
        engine: The engine producing frames.
    """

    def __init__(self, window, engine):
        self.window = window
        self.engine = engine
        #: While true, playback sticks to the newest available frame.
        self.following = True
        self._last_metadata_refresh = 0.0
        self._badge = arcade.Text("LIVE", 0, 0, BADGE_TEXT_COLOR, 14, bold=True)
        self._hint = arcade.Text("", 0, 0, (210, 210, 210), 11)

    # -- playback --------------------------------------------------------

    @property
    def latest_index(self) -> int:
        return max(0, len(self.window.frames) - 1)

    def frames_behind(self) -> int:
        """How many frames the viewer is behind the live edge."""
        return max(0, self.latest_index - int(self.window.frame_index))

    def seconds_behind(self) -> float:
        from src.f1_data import FPS

        return self.frames_behind() / float(FPS)

    def go_live(self) -> None:
        """Jump back to the newest frame and resume following it."""
        self.following = True
        self.window.paused = False
        self.window.playback_speed = 1.0
        self.window.frame_index = float(self.latest_index)

    def leave_live(self) -> None:
        """Stop following the live edge (the viewer took manual control)."""
        self.following = False

    def on_update(self, delta_time: float) -> None:
        """Advance playback. Returns nothing; call instead of the default."""
        self._refresh_metadata()

        if not self.following:
            return

        target = self.latest_index - LIVE_FOLLOW_LAG_FRAMES
        if target < 0:
            return
        # Snap forward to the live edge. Frames are produced on the session
        # clock, so following the tail keeps playback at real speed without
        # accumulating drift.
        self.window.frame_index = float(target)

    # -- metadata --------------------------------------------------------

    def _refresh_metadata(self) -> None:
        now = time.monotonic()
        if now - self._last_metadata_refresh < METADATA_REFRESH_S:
            return
        self._last_metadata_refresh = now

        window = self.window
        try:
            window.track_statuses = self.engine.track_statuses()

            total_laps = self.engine.total_laps()
            if total_laps and total_laps != window.total_laps:
                window.total_laps = total_laps
                window.session_info_comp.session_info["total_laps"] = total_laps

            # Weather only starts arriving once the session is under way, so
            # the panel has to be enabled after the window was built.
            if not window.has_weather:
                latest = window.frames.latest if window.frames else None
                window.has_weather = bool(latest and "weather" in latest)

            colors = self.engine.driver_colors()
            if colors:
                window.driver_colors.update(colors)

            messages = list(self.engine.state.race_control_messages)
            if len(messages) != len(window.race_control_messages):
                window.race_control_messages = messages

            window.progress_bar_comp.set_race_data(
                total_frames=max(1, len(window.frames)),
                total_laps=window.total_laps or 0,
                events=[],
            )
        except Exception as exc:
            print(f"[live] could not refresh session metadata: {exc}")

        # Pit stop times are published separately from the live feed, so a
        # problem fetching them must not hold up anything above.
        try:
            stops = self.engine.state.pit_stops_by_code()
            tower = getattr(window, "leaderboard_comp", None)
            if stops and tower is not None:
                tower.pit_times = stops

            from src.lib.position_history import to_payload

            history = self.engine.state.position_history
            if history:
                window._position_history = to_payload(history)

            prediction = self.engine.state.championship_prediction
            if prediction:
                window.championship_prediction = prediction
        except Exception as exc:
            print(f"[live] pit stop times unavailable: {exc}")

    # -- input -----------------------------------------------------------

    def on_key_press(self, symbol: int) -> bool:
        """Handle live-specific keys. Returns True when the key was consumed."""
        if symbol == arcade.key.G:
            self.go_live()
            return True
        # Anything that seeks or pauses means the viewer wants manual control.
        if symbol in (arcade.key.SPACE, arcade.key.LEFT, arcade.key.RIGHT,
                      arcade.key.R, arcade.key.UP, arcade.key.DOWN,
                      arcade.key.KEY_1, arcade.key.KEY_2, arcade.key.KEY_3,
                      arcade.key.KEY_4):
            self.leave_live()
        return False

    # -- drawing ---------------------------------------------------------

    def draw_badge(self) -> None:
        """Draw the live indicator in the top right of the window."""
        window = self.window
        behind = self.seconds_behind()
        live = self.following and behind < 2.0

        if live:
            label = "● LIVE"
            color = BADGE_LIVE_COLOR
            hint = self.engine.status_text()
        else:
            label = f"◀ -{behind:0.0f}s"
            color = BADGE_BEHIND_COLOR
            hint = "press G to go live"

        right = window.width - 20
        top = window.height - 24

        self._badge.text = label
        self._badge.x = right - 90
        self._badge.y = top
        self._badge.color = BADGE_TEXT_COLOR

        arcade.draw_lrbt_rectangle_filled(
            left=right - 100, right=right, bottom=top - 6, top=top + 20,
            color=color,
        )
        self._badge.draw()

        self._hint.text = hint
        self._hint.x = right - 100 - max(0, len(hint) * 6)
        self._hint.y = top + 2
        self._hint.draw()
