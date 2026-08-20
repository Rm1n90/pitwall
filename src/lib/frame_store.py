"""Storing computed telemetry frames.

A race is about 150,000 frames of roughly twenty cars, and writing that as a
list of dictionaries costs close to half a gigabyte per session. The numbers
themselves are a small part of that: most of it is Python object overhead
repeated three million times.

Storing one array per driver per channel instead, at single precision, brings
a race down to around a twentieth of the size. Frames are rebuilt on load, so
nothing that reads them needs to know.

Two fields are recomputed rather than stored: ``dist`` and ``rel_dist``, both
of which follow from ``progress``. For ``dist`` that is exactly what the
pipeline itself does. ``rel_dist`` is the one value that comes back slightly
different, because the pipeline takes it from the raw feed while ``progress``
is the repaired, speed-integrated figure the running order is built on; the
two disagree by more than a hundredth of a lap about one sample in a hundred,
at worst four hundredths. Deriving it keeps a frame self-consistent, and
nothing outside the pipeline reads the field.
"""

import os
import pickle
from typing import Dict, List, Optional

import numpy as np

# Bumped when the stored layout changes in a way older readers cannot handle.
FORMAT_VERSION = 3

# Channels held per driver per frame. Anything derivable is left out and
# recomputed on load.
DRIVER_CHANNELS = (
    "x", "y", "progress", "lap", "tyre", "tyre_life", "speed", "gear",
    "drs", "throttle", "brake", "position", "pit_stops",
)
BOOL_CHANNELS = ("in_pit", "retired")

# Weather is per frame rather than per driver.
WEATHER_CHANNELS = ("track_temp", "air_temp", "humidity", "wind_speed",
                    "wind_direction")

SAFETY_CAR_PHASES = ("deploying", "on_track", "returning")

# Channels stored as whole numbers, so they come back as ints not floats.
INTEGER_CHANNELS = {"lap", "gear", "drs", "position", "pit_stops"}

_META_KEY = "__meta__"


def _or_nan(value):
    """Represent a missing reading as NaN so it survives a float array."""
    return float("nan") if value is None else float(value)


def _or_none(value):
    """Turn the NaN written by :func:`_or_nan` back into ``None``."""
    return None if value != value else float(value)


def _driver_columns(frames, codes):
    """Fill every driver channel in one pass over the frames.

    A pass per channel would mean walking the whole race a few hundred times.
    """
    count = len(frames)
    # Each channel is stored in its natural type, so reading it back with
    # tolist() already produces Python ints and bools and the load does not
    # have to convert three million values by hand.
    numeric = {
        (code, channel): np.zeros(
            count, dtype=np.int32 if channel in INTEGER_CHANNELS
            else np.float32)
        for code in codes for channel in DRIVER_CHANNELS
    }
    flags = {(code, channel): np.zeros(count, dtype=bool)
             for code in codes for channel in BOOL_CHANNELS}
    present = {code: np.zeros(count, dtype=bool) for code in codes}

    for index, frame in enumerate(frames):
        for code, car in frame["drivers"].items():
            if code not in present:
                continue
            present[code][index] = True
            for channel in DRIVER_CHANNELS:
                numeric[(code, channel)][index] = car.get(channel) or 0
            for channel in BOOL_CHANNELS:
                flags[(code, channel)][index] = bool(car.get(channel))

    return numeric, flags, present


def save(path: str, data: dict, lap_length_m: float = 0.0) -> None:
    """Write computed telemetry to ``path``.

    Args:
        path: Destination file.
        data: The dictionary returned by the telemetry pipeline.
        lap_length_m: Lap length, needed to rebuild race distance on load.
    """
    frames = data["frames"]
    codes = sorted({code for frame in frames for code in frame["drivers"]})

    arrays: Dict[str, np.ndarray] = {} if not frames else {
        "t": np.array([f["t"] for f in frames], dtype=np.float32),
        "lap": np.array([f.get("lap", 1) for f in frames], dtype=np.int16),
    }

    numeric, flags, present = _driver_columns(frames, codes)
    for code in codes:
        arrays[f"present|{code}"] = present[code]
        for channel in DRIVER_CHANNELS:
            arrays[f"d|{code}|{channel}"] = numeric[(code, channel)]
        for channel in BOOL_CHANNELS:
            arrays[f"d|{code}|{channel}"] = flags[(code, channel)]

    if any(f.get("weather") for f in frames):
        # A frame can have no weather at all, and a weather snapshot can be
        # missing individual readings. Both are recorded rather than being
        # flattened to zero, which would show up on screen as 0 degrees.
        readings = [f.get("weather") or {} for f in frames]
        arrays["w|present"] = np.array([bool(w) for w in readings], dtype=bool)
        for channel in WEATHER_CHANNELS:
            arrays[f"w|{channel}"] = np.array(
                [_or_nan(w.get(channel)) for w in readings], dtype=np.float32)
        arrays["w|raining"] = np.array(
            [w.get("rain_state") == "RAINING" for w in readings], dtype=bool)

    if any(f.get("time_remaining_s") is not None for f in frames):
        arrays["time_remaining_s"] = np.array(
            [_or_nan(f.get("time_remaining_s")) for f in frames],
            dtype=np.float32)

    if any(f.get("safety_car") for f in frames):
        cars = [f.get("safety_car") or {} for f in frames]
        arrays["sc|x"] = np.array([c.get("x") or 0.0 for c in cars],
                                  dtype=np.float32)
        arrays["sc|y"] = np.array([c.get("y") or 0.0 for c in cars],
                                  dtype=np.float32)
        arrays["sc|alpha"] = np.array([c.get("alpha") or 0.0 for c in cars],
                                      dtype=np.float32)
        arrays["sc|phase"] = np.array(
            [SAFETY_CAR_PHASES.index(c["phase"])
             if c.get("phase") in SAFETY_CAR_PHASES else -1
             for c in cars], dtype=np.int8)

    meta = {key: value for key, value in data.items() if key != "frames"}
    meta["__format__"] = FORMAT_VERSION
    meta["__codes__"] = codes
    meta["__lap_length_m__"] = float(lap_length_m)
    arrays[_META_KEY] = np.frombuffer(
        pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL), dtype=np.uint8)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.savez_compressed(path, **arrays)


def _rebuild_frames(stored, codes: List[str], lap_length_m: float) -> List[dict]:
    """Turn stored columns back into the frame dictionaries readers expect."""
    if "t" not in stored:
        return []
    times = stored["t"]
    leader_laps = stored["lap"]
    lap_length_m = float(lap_length_m)
    count = len(times)

    # Converting each column to a Python list once, then zipping, is far
    # cheaper than indexing numpy arrays three million times.
    keys = list(DRIVER_CHANNELS) + list(BOOL_CHANNELS)
    progress_at = keys.index("progress")

    per_driver = []
    for code in codes:
        columns = [stored[f"d|{code}|{channel}"].tolist() for channel in keys]
        per_driver.append((code, stored[f"present|{code}"].tolist(),
                           list(zip(*columns))))

    # Reading a member of a compressed archive decompresses it in full, so
    # everything the loop needs is pulled into memory first.
    weather = None
    if "w|raining" in stored:
        weather = {channel: stored[f"w|{channel}"].tolist()
                   for channel in WEATHER_CHANNELS}
        weather["raining"] = stored["w|raining"].tolist()
        weather["present"] = (
            stored["w|present"].tolist() if "w|present" in stored
            else [True] * count)

    remaining = (stored["time_remaining_s"].tolist()
                 if "time_remaining_s" in stored else None)

    safety_car = None
    if "sc|phase" in stored:
        safety_car = {key: stored[f"sc|{key}"].tolist()
                      for key in ("x", "y", "alpha", "phase")}

    frames = []
    time_values = times.tolist()
    lap_values = leader_laps.tolist()

    for index in range(count):
        drivers = {}
        for code, present, rows in per_driver:
            if not present[index]:
                continue
            values = rows[index]
            car = dict(zip(keys, values))
            # Derived from progress, so not stored.
            progress = values[progress_at]
            car["dist"] = progress * lap_length_m
            car["rel_dist"] = round(progress - int(progress), 4)
            drivers[code] = car

        frame = {"t": time_values[index], "lap": lap_values[index],
                 "drivers": drivers}

        if weather is not None and weather["present"][index]:
            frame["weather"] = {channel: _or_none(weather[channel][index])
                                for channel in WEATHER_CHANNELS}
            frame["weather"]["rain_state"] = \
                "RAINING" if weather["raining"][index] else "DRY"

        if remaining is not None:
            frame["time_remaining_s"] = _or_none(remaining[index])

        if safety_car is not None:
            phase = int(safety_car["phase"][index])
            frame["safety_car"] = None if phase < 0 else {
                "x": float(safety_car["x"][index]),
                "y": float(safety_car["y"][index]),
                "alpha": float(safety_car["alpha"][index]),
                "phase": SAFETY_CAR_PHASES[phase],
            }

        frames.append(frame)
    return frames


def load(path: str) -> Optional[dict]:
    """Read computed telemetry from ``path``.

    Returns ``None`` if the file is missing or unreadable, so a caller can
    fall back to recomputing.
    """
    if not os.path.exists(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as stored:
            meta = pickle.loads(stored[_META_KEY].tobytes())
            codes = meta.pop("__codes__")
            lap_length_m = meta.pop("__lap_length_m__", 0.0)
            meta.pop("__format__", None)
            frames = _rebuild_frames(stored, codes, lap_length_m)
    except Exception as e:
        print(f"Could not read the cached telemetry: {e}")
        return None

    meta["frames"] = frames
    return meta
