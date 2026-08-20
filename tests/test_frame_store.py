"""Tests for the compact on-disk race cache."""

import os
import tempfile
import unittest

from src.lib import frame_store


def make_frame(t, lap, codes=("VER", "NOR"), **overrides):
    """A frame in the shape produced by src/f1_data.py."""
    drivers = {}
    for index, code in enumerate(codes):
        drivers[code] = {
            "x": 100.0 + index,
            "y": 200.0 + index,
            "dist": 500.0 * (lap - 1) + 10.0 * index,
            "lap": lap,
            "rel_dist": 10.0 * index,
            "progress": (lap - 1) + 0.01 * index,
            "tyre": 1,
            "tyre_life": 4.0 + index,
            "speed": 250.0 - index,
            "gear": 7,
            "drs": 8,
            "throttle": 100.0,
            "brake": 0.0,
            "in_pit": False,
            "pit_stops": 1,
            "position": index + 1,
            "retired": False,
        }
    frame = {
        "t": t,
        "lap": lap,
        "drivers": drivers,
        "weather": None,
        "safety_car": None,
        "time_remaining_s": None,
    }
    frame.update(overrides)
    return frame


def payload(frames, **extra):
    data = {
        "frames": frames,
        "driver_colors": {"VER": (1, 33, 243)},
        "track_statuses": [],
        "race_control_messages": [],
        "total_laps": 70,
        "max_tyre_life": {"VER": 30},
    }
    data.update(extra)
    return data


class RoundTripTest(unittest.TestCase):

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".npz")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def save_and_load(self, data, lap_length_m=5000.0):
        frame_store.save(self.path, data, lap_length_m=lap_length_m)
        loaded = frame_store.load(self.path)
        self.assertIsNotNone(loaded)
        return loaded

    def test_frames_survive_the_round_trip(self):
        frames = [make_frame(0.0, 1), make_frame(1.0, 2)]
        loaded = self.save_and_load(payload(frames))

        self.assertEqual(len(loaded["frames"]), 2)
        for original, restored in zip(frames, loaded["frames"]):
            self.assertAlmostEqual(original["t"], restored["t"], places=3)
            self.assertEqual(original["lap"], restored["lap"])
            self.assertEqual(set(original["drivers"]), set(restored["drivers"]))

    def test_metadata_survives_the_round_trip(self):
        loaded = self.save_and_load(payload([make_frame(0.0, 1)]))

        self.assertEqual(loaded["total_laps"], 70)
        self.assertEqual(loaded["max_tyre_life"], {"VER": 30})
        self.assertEqual(loaded["driver_colors"], {"VER": (1, 33, 243)})

    def test_integer_channels_come_back_as_integers(self):
        loaded = self.save_and_load(payload([make_frame(0.0, 3)]))
        car = loaded["frames"][0]["drivers"]["VER"]

        for channel in ("lap", "gear", "drs", "position", "pit_stops"):
            self.assertIsInstance(car[channel], int, channel)

    def test_flags_come_back_as_booleans(self):
        frames = [make_frame(0.0, 1)]
        frames[0]["drivers"]["NOR"]["in_pit"] = True
        frames[0]["drivers"]["NOR"]["retired"] = True
        loaded = self.save_and_load(payload(frames))

        car = loaded["frames"][0]["drivers"]["NOR"]
        self.assertIs(car["in_pit"], True)
        self.assertIs(car["retired"], True)
        self.assertIs(loaded["frames"][0]["drivers"]["VER"]["in_pit"], False)

    def test_distance_is_derived_from_progress(self):
        # dist and rel_dist are not stored; they are recomputed on load, which
        # is why the lap length has to be saved alongside the frames.
        frames = [make_frame(0.0, 3)]
        frames[0]["drivers"]["VER"]["progress"] = 2.5
        loaded = self.save_and_load(payload(frames), lap_length_m=4000.0)

        car = loaded["frames"][0]["drivers"]["VER"]
        self.assertAlmostEqual(car["dist"], 10000.0, places=1)
        # rel_dist is the fraction of the current lap completed, not metres.
        self.assertAlmostEqual(car["rel_dist"], 0.5, places=3)

    def test_drivers_missing_from_a_frame_stay_missing(self):
        # Cars that retire stop appearing in later frames.
        frames = [make_frame(0.0, 1), make_frame(1.0, 2, codes=("VER",))]
        loaded = self.save_and_load(payload(frames))

        self.assertIn("NOR", loaded["frames"][0]["drivers"])
        self.assertNotIn("NOR", loaded["frames"][1]["drivers"])

    def test_weather_survives_the_round_trip(self):
        weather = {
            "track_temp": 49.5, "air_temp": 31.0, "humidity": 26.0,
            "wind_speed": 2.0, "wind_direction": 127.0, "rain_state": "DRY",
        }
        frames = [make_frame(0.0, 1, weather=weather), make_frame(1.0, 1)]
        loaded = self.save_and_load(payload(frames))

        restored = loaded["frames"][0]["weather"]
        self.assertEqual(restored["rain_state"], "DRY")
        self.assertAlmostEqual(restored["track_temp"], 49.5, places=2)
        # The pipeline leaves the key off entirely when it has no snapshot.
        self.assertIsNone(loaded["frames"][1].get("weather"))

    def test_safety_car_survives_the_round_trip(self):
        on_track = {"x": 10.0, "y": 20.0, "alpha": 1.0, "phase": "on_track"}
        deploying = {"x": 11.0, "y": 21.0, "alpha": 0.5, "phase": "deploying"}
        frames = [make_frame(0.0, 1, safety_car=on_track),
                  make_frame(1.0, 1, safety_car=deploying),
                  make_frame(2.0, 1)]
        loaded = self.save_and_load(payload(frames))

        self.assertEqual(loaded["frames"][0]["safety_car"], on_track)
        self.assertEqual(loaded["frames"][1]["safety_car"], deploying)
        self.assertIsNone(loaded["frames"][2]["safety_car"])

    def test_time_remaining_survives_the_round_trip(self):
        frames = [make_frame(0.0, 1, time_remaining_s=3600.0),
                  make_frame(1.0, 1)]
        loaded = self.save_and_load(payload(frames))

        self.assertAlmostEqual(loaded["frames"][0]["time_remaining_s"],
                               3600.0, places=1)
        self.assertIsNone(loaded["frames"][1]["time_remaining_s"])

    def test_empty_frame_list_round_trips(self):
        loaded = self.save_and_load(payload([]))
        self.assertEqual(loaded["frames"], [])
        self.assertEqual(loaded["total_laps"], 70)

    def test_weather_readings_that_are_missing_stay_missing(self):
        # A reading the feed never published must not come back as zero, or
        # the display would show a track temperature of 0 degrees.
        weather = {
            "track_temp": None, "air_temp": 31.0, "humidity": None,
            "wind_speed": 2.0, "wind_direction": 127.0, "rain_state": "DRY",
        }
        loaded = self.save_and_load(payload([make_frame(0.0, 1,
                                                        weather=weather)]))

        restored = loaded["frames"][0]["weather"]
        self.assertIsNone(restored["track_temp"])
        self.assertIsNone(restored["humidity"])
        self.assertAlmostEqual(restored["air_temp"], 31.0, places=2)

    def test_rain_survives_the_round_trip(self):
        weather = {"track_temp": 18.0, "air_temp": 14.0, "humidity": 90.0,
                   "wind_speed": 4.0, "wind_direction": 200.0,
                   "rain_state": "RAINING"}
        loaded = self.save_and_load(payload([make_frame(0.0, 1,
                                                        weather=weather)]))
        self.assertEqual(loaded["frames"][0]["weather"]["rain_state"],
                         "RAINING")


class LoadFailureTest(unittest.TestCase):

    def test_missing_file_returns_none(self):
        # The caller falls back to recomputing rather than crashing.
        self.assertIsNone(frame_store.load("/nonexistent/race.npz"))

    def test_corrupt_file_returns_none(self):
        handle, path = tempfile.mkstemp(suffix=".npz")
        with os.fdopen(handle, "wb") as f:
            f.write(b"this is not a numpy archive")
        try:
            self.assertIsNone(frame_store.load(path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
