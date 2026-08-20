"""Turns live session state into replay frames.

The output is deliberately identical in shape to the frames produced by
:func:`src.f1_data.get_race_telemetry`, so the replay window, the leaderboard,
the telemetry stream and every insight window keep working untouched. Live
mode only adds extra keys, never removes any.
"""

from typing import Dict, List, Optional

from src.live.projection import TrackProjector
from src.live.state import LiveSessionState
from src.lib.tyres import get_tyre_compound_int

# Distance the simulated safety car runs ahead of the leader, matching the
# behaviour of the offline replay.
SC_LEAD_DISTANCE_M = 500.0

# Track status codes that put the safety car on track.
SC_STATUS_CODES = ("4",)

# Seconds the safety car takes to animate out of, and back into, the pits.
SC_TRANSITION_S = 3.0


class LiveFrameBuilder:
    """Builds one replay frame per call from the current live state.

    Args:
        state: The session state being filled by the data sources.
        projector: Track geometry used to derive lap fractions.
    """

    def __init__(self, state: LiveSessionState, projector: TrackProjector):
        self.state = state
        self.projector = projector
        self._last_lap: Dict[str, int] = {}
        self._sc_started_t: Optional[float] = None
        self._sc_ended_t: Optional[float] = None
        self._was_sc = False

    # -- per driver ------------------------------------------------------

    def _tyre_for(self, number: str, lap: int) -> tuple:
        """Return ``(compound_int, tyre_life)`` for a driver's current stint."""
        stint = self.state.current_stint(number)
        # The compound is unknown until a driver's first stint is published.
        raw_compound = stint.get("Compound")
        compound = get_tyre_compound_int(raw_compound) if raw_compound else -1

        # The feed keeps 'TotalLaps' up to date as the running age of the
        # current set, which is exactly what the leaderboard wants.
        try:
            return compound, float(stint["TotalLaps"])
        except (KeyError, TypeError, ValueError):
            pass

        # Older or partial stint entries only say when the set was fitted.
        try:
            fitted_on_lap = int(stint.get("LapNumber") or 0)
        except (TypeError, ValueError):
            fitted_on_lap = 0
        try:
            age_when_fitted = float(stint.get("StartLaps") or 0)
        except (TypeError, ValueError):
            age_when_fitted = 0.0

        laps_on_set = max(0, lap - fitted_on_lap) if fitted_on_lap else 0
        return compound, float(age_when_fitted + laps_on_set)

    def _lap_for(self, number: str, timing: dict) -> int:
        """Return the driver's current lap, never going backwards."""
        raw = timing.get("NumberOfLaps")
        try:
            lap = int(raw)
        except (TypeError, ValueError):
            lap = self._last_lap.get(number, self.state.current_lap())
        lap = max(1, lap)
        previous = self._last_lap.get(number)
        if previous is not None and lap < previous:
            lap = previous
        self._last_lap[number] = lap
        return lap

    def _sample_driver(self, number: str, t: float) -> Optional[tuple]:
        """Return ``(x, y, on_track)`` for a driver, or ``None`` to skip them."""
        samples = self.state.samples.get(number)
        if samples is None:
            return None
        position = samples.position_at(t, self.state.track_line)
        if position is None:
            return None

        x, y, on_track = position
        timing = self.state.timing.get(number) or {}
        if (timing.get("Retired") or timing.get("Stopped")) and not on_track:
            # Retired cars stay in the timing feed but must not be drawn as
            # if they were still circulating.
            return None
        return x, y, on_track

    def _driver_entry(self, number: str, t: float, x: float, y: float,
                      on_track: bool, rel_dist: float) -> dict:
        """Build the frame entry for one driver."""
        timing = self.state.timing.get(number) or {}
        samples = self.state.samples.get(number)
        lap = self._lap_for(number, timing)
        compound, tyre_life = self._tyre_for(number, lap)
        car = (samples.car_at(t) if samples is not None else None) or {}

        try:
            running_position = int(timing.get("Position"))
        except (TypeError, ValueError):
            running_position = None

        interval = timing.get("IntervalToPositionAhead")
        if isinstance(interval, dict):
            interval = interval.get("Value", "")

        progress = (lap - 1) + rel_dist
        return {
            "x": x,
            "y": y,
            "dist": progress * self.projector.length_m,
            "lap": lap,
            "rel_dist": round(rel_dist, 4),
            # Race progress in laps, matching the offline replay frames.
            "progress": round(progress, 6),
            "tyre": float(compound),
            "tyre_life": tyre_life,
            "position": running_position,
            "speed": float(car.get("speed", 0.0)),
            "gear": int(car.get("gear", 0)),
            "drs": int(car.get("drs", 0)),
            "throttle": float(car.get("throttle", 0.0)),
            "brake": float(car.get("brake", 0.0)),
            "in_pit": bool(timing.get("InPit", False)),
            # Live-only extras; existing consumers ignore unknown keys.
            # Offline these come from the lap table, which does not exist
            # while a session is still running.
            "last_lap_s": self.state.last_lap_time(number),
            "best_lap_s": self.state.best_lap_time(number),
            "sectors": self.state.sector_status(number),
            "gap_to_leader": str(timing.get("GapToLeader", "") or ""),
            "interval": str(interval or ""),
            "retired": bool(timing.get("Retired", False)),
            "on_track": bool(on_track),
        }

    # -- whole frame -----------------------------------------------------

    def _assign_positions(self, drivers: Dict[str, dict]) -> None:
        """Fill in any missing running positions.

        The official ``Position`` field is authoritative and far more accurate
        than sorting by distance, but a driver can briefly appear before their
        first timing update. Those are appended behind the ranked cars.
        """
        ranked = [(entry["position"], code)
                  for code, entry in drivers.items()
                  if entry.get("position")]
        used = {position for position, _ in ranked}
        next_free = max(used) + 1 if used else 1

        for code, entry in drivers.items():
            if entry.get("position"):
                continue
            while next_free in used:
                next_free += 1
            entry["position"] = next_free
            used.add(next_free)

    def _weather(self) -> dict:
        weather = self.state.weather
        if not weather:
            return {}

        def _number(key):
            try:
                return float(weather.get(key))
            except (TypeError, ValueError):
                return None

        rainfall = _number("Rainfall") or 0.0
        return {
            "track_temp": _number("TrackTemp"),
            "air_temp": _number("AirTemp"),
            "humidity": _number("Humidity"),
            "wind_speed": _number("WindSpeed"),
            "wind_direction": _number("WindDirection"),
            "rain_state": "RAINING" if rainfall >= 0.5 else "DRY",
        }

    def _safety_car(self, t: float, drivers: Dict[str, dict]) -> Optional[dict]:
        """Simulate the safety car position, mirroring the offline replay.

        F1 publishes no GPS for the safety car, so it is drawn ahead of the
        race leader while track status reports a deployment.
        """
        status = str(self.state.track_status.get("Status", "1"))
        deployed = status in SC_STATUS_CODES

        if deployed and not self._was_sc:
            self._sc_started_t = t
            self._sc_ended_t = None
        elif not deployed and self._was_sc:
            self._sc_ended_t = t
        self._was_sc = deployed

        if not deployed:
            if self._sc_ended_t is None:
                return None
            elapsed = t - self._sc_ended_t
            if elapsed > SC_TRANSITION_S:
                return None
            phase, alpha = "returning", max(0.0, 1.0 - elapsed / SC_TRANSITION_S)
        else:
            elapsed = t - (self._sc_started_t or t)
            if elapsed < SC_TRANSITION_S:
                phase = "deploying"
                alpha = min(1.0, elapsed / SC_TRANSITION_S)
            else:
                phase, alpha = "on_track", 1.0

        leader = min(
            (entry for entry in drivers.values() if entry.get("position")),
            key=lambda entry: entry["position"],
            default=None,
        )
        if leader is None:
            return None

        ahead = self.projector.advance(leader["rel_dist"], SC_LEAD_DISTANCE_M)
        x, y = self.projector.point_at(ahead)
        return {"x": x, "y": y, "phase": phase, "alpha": round(alpha, 3)}

    def build(self, t: float) -> Optional[dict]:
        """Build the frame for render time ``t`` (seconds since session start).

        Returns ``None`` when no car has a position sample yet.
        """
        state = self.state
        with state.lock:
            numbers = []
            points = []
            flags = []
            for number in list(state.samples.keys()):
                sample = self._sample_driver(number, t)
                if sample is None:
                    continue
                numbers.append(number)
                points.append((sample[0], sample[1]))
                flags.append(sample[2])

            if not numbers:
                return None

            # One batched projection per frame rather than one per car.
            rel_dists = self.projector.relative_distances(points)

            drivers = {}
            for index, number in enumerate(numbers):
                x, y = points[index]
                entry = self._driver_entry(
                    number, t, x, y, flags[index], float(rel_dists[index])
                )
                drivers[state.driver_code(number)] = entry

            self._assign_positions(drivers)
            leader_lap = max(
                (entry["lap"] for entry in drivers.values()), default=1
            )
            frame = {
                "t": round(t, 3),
                "lap": leader_lap,
                "drivers": drivers,
            }
            weather = self._weather()
            if weather:
                frame["weather"] = weather

            remaining = state.time_remaining_s(t)
            if remaining is not None:
                frame["time_remaining_s"] = remaining
            frame["safety_car"] = self._safety_car(t, drivers)
            return frame


def build_track_statuses(state: LiveSessionState) -> List[dict]:
    """Return the track status timeline in the shape the replay expects."""
    return [
        {
            "status": entry["status"],
            "start_time": entry["start_time"],
            "end_time": entry["end_time"],
        }
        for entry in state.resolved_track_status_history()
    ]
