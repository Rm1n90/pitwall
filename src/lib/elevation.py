"""Track elevation, taken from the position feed.

Every position sample carries a Z channel alongside X and Y: absolute
altitude in tenths of a metre. At the Hungaroring it runs from 204 m to
239 m, which is the circuit's real 35 m of elevation change, and it is
smooth enough to use directly once the gaps are filled.

The feed writes zero when it has no altitude rather than leaving the field
out, and about one sample in nine is missing that way.
"""

import os
import pickle
from typing import Optional

import numpy as np

#: The feed reports altitude in tenths of a metre.
TENTHS_PER_METRE = 10.0

#: How many reference points to average over when smoothing. The profile is
#: sampled far more finely than the elevation actually changes.
DEFAULT_SMOOTHING_WINDOW = 15

_CACHE_DIR = os.path.join("computed_data", "elevation")


def to_metres(raw: np.ndarray) -> np.ndarray:
    """Convert raw Z samples to metres, with missing readings as NaN."""
    values = np.asarray(raw, dtype=float)
    metres = values / TENTHS_PER_METRE
    # A circuit is never at sea level, so zero means "no reading".
    return np.where(values > 0, metres, np.nan)


def fill_gaps(profile: np.ndarray) -> np.ndarray:
    """Interpolate across missing points, treating the lap as a loop.

    A gap that spans the start line is filled from the points either side of
    it rather than being clamped, because the finish line is not the end of
    anything.
    """
    values = np.asarray(profile, dtype=float).copy()
    known = np.isfinite(values)
    if not known.any():
        # Better a flat circuit than no circuit.
        return np.zeros_like(values)
    if known.all():
        return values

    count = len(values)
    indices = np.arange(count, dtype=float)
    # Repeating the known points a lap either side makes the interpolation
    # wrap without any special handling at the seam.
    known_at = indices[known]
    known_values = values[known]
    wrapped_at = np.concatenate(
        [known_at - count, known_at, known_at + count])
    wrapped_values = np.tile(known_values, 3)
    return np.interp(indices, wrapped_at, wrapped_values)


def smooth(profile: np.ndarray, window: int = DEFAULT_SMOOTHING_WINDOW
           ) -> np.ndarray:
    """Average over neighbouring points, wrapping around the lap."""
    values = np.asarray(profile, dtype=float)
    if window <= 1 or len(values) < 3:
        return values.copy()

    window = min(int(window), len(values))
    if window % 2 == 0:
        window += 1
    padding = window // 2
    padded = np.concatenate(
        [values[-padding:], values, values[:padding]])
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")[:len(values)]


def rebase(profile: np.ndarray) -> np.ndarray:
    """Shift the profile so the lowest point of the circuit sits at zero."""
    values = np.asarray(profile, dtype=float)
    if not len(values):
        return values
    return values - np.nanmin(values)


def _cache_path(event_key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in event_key)
    return os.path.join(_CACHE_DIR, f"{safe}.pkl")


def load_cached(event_key: str) -> Optional[np.ndarray]:
    """Read a previously built profile, or ``None`` if there is not one."""
    try:
        with open(_cache_path(event_key), "rb") as handle:
            return pickle.load(handle)
    except (FileNotFoundError, EOFError, pickle.UnpicklingError):
        return None


def save_cached(event_key: str, profile: np.ndarray) -> None:
    """Keep a built profile so the next run does not rebuild it."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(event_key), "wb") as handle:
            pickle.dump(profile, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError as exc:
        print(f"Could not cache the elevation profile: {exc}")


def build_profile(session, track_x, track_y,
                  event_key: Optional[str] = None,
                  smoothing: int = DEFAULT_SMOOTHING_WINDOW) -> np.ndarray:
    """Elevation in metres for every point on a reference line.

    Args:
        session: A loaded FastF1 session, for its position data.
        track_x: Reference line X coordinates, in feed units.
        track_y: Reference line Y coordinates, in feed units.
        event_key: Cache key. Building the profile means a nearest-point
            lookup over every position sample of the session.
        smoothing: How many reference points to average over.

    Returns:
        One elevation per reference point, in metres, with the lowest point
        of the circuit at zero. A flat profile is returned rather than
        raising if the session has no usable altitude.
    """
    if event_key:
        cached = load_cached(event_key)
        if cached is not None and len(cached) == len(track_x):
            return cached

    reference = np.column_stack([np.asarray(track_x, dtype=float),
                                 np.asarray(track_y, dtype=float)])
    flat = np.zeros(len(reference))

    samples = []
    for frame in (getattr(session, "pos_data", None) or {}).values():
        if frame is None or not len(frame) or "Z" not in frame:
            continue
        x = frame["X"].to_numpy(dtype=float)
        y = frame["Y"].to_numpy(dtype=float)
        z = to_metres(frame["Z"].to_numpy(dtype=float))
        usable = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        if usable.any():
            samples.append(np.column_stack([x[usable], y[usable], z[usable]]))

    if not samples:
        print("No altitude in the position feed; the circuit will be flat.")
        return flat

    points = np.vstack(samples)
    try:
        from scipy.spatial import cKDTree

        _, nearest = cKDTree(reference).query(points[:, :2])
    except Exception as exc:
        print(f"Could not match altitude to the track: {exc}")
        return flat

    # The median rather than the mean: a car bouncing over a kerb, or a
    # stray sample from the pit lane, should not lift the whole corner.
    profile = np.full(len(reference), np.nan)
    order = np.argsort(nearest)
    sorted_index = nearest[order]
    sorted_z = points[order, 2]
    edges = np.searchsorted(sorted_index, np.arange(len(reference) + 1))
    for point in range(len(reference)):
        start, end = edges[point], edges[point + 1]
        if end > start:
            profile[point] = np.median(sorted_z[start:end])

    profile = rebase(smooth(fill_gaps(profile), smoothing))
    if event_key:
        save_cached(event_key, profile)
    return profile
