"""Reconstruct a MotoGP replay from per-lap sector times.

MotoGP publishes no positional feed, only four intermediate split times per
lap. This module is the mirror of :func:`src.lib.track_geometry.rebuild_positions`:
where that walks an F1 car along the centreline at the speed the feed reports,
this walks a bike along the centreline at the pace its sector times imply.

Each lap is divided into four segments at the intermediates. Their exact
positions on the circuit are not published, so v1 places them at equal quarters
of the lap; a bike then covers each quarter at the constant speed its split
time implies, which is fast on a quick sector and slow on a twisty one. The
output is the same ``frames`` structure the replay window consumes for F1, so
everything downstream — timing tower, insights, telemetry stream — works
unchanged.
"""

from typing import Dict, List, Optional

import numpy as np

# Colour used when a rider has no team colour available.
_DEFAULT_COLOUR = (200, 200, 200)

# Intermediates split the lap into this many equal-distance segments (v1).
_SEGMENTS = 4


def _compound_int(name):
    """Map a MotoGP tyre name (e.g. ``Slick-Soft``) to the shared tyre integer."""
    from src.lib.tyres import get_tyre_compound_int
    if not name:
        return -1
    text = str(name).upper()
    for compound in ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"):
        if compound in text:
            return get_tyre_compound_int(compound)
    return -1


def _hex_to_rgb(value: Optional[str]):
    if not value:
        return _DEFAULT_COLOUR
    text = value.lstrip("#")
    if len(text) != 6:
        return _DEFAULT_COLOUR
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return _DEFAULT_COLOUR


def _segment_times(lap):
    """The four segment times for a lap, falling back to equal splits."""
    sectors = [s for s in lap.sectors if s is not None]
    if len(sectors) == _SEGMENTS and all(s > 0 for s in sectors):
        return list(lap.sectors)
    if lap.lap_time_s and lap.lap_time_s > 0:
        return [lap.lap_time_s / _SEGMENTS] * _SEGMENTS
    return None


def _rider_timeline(rider, length_m):
    """Build monotonic (time, distance, speed) anchors for one rider.

    Returns arrays ``times`` and ``dists`` plus a per-anchor ``speeds`` in
    km/h, or ``None`` if the rider has no usable lap.
    """
    seg_distance = length_m / _SEGMENTS
    times = [0.0]
    dists = [0.0]
    speeds = [0.0]
    t = 0.0
    d = 0.0
    for lap in rider.laps:
        seg_times = _segment_times(lap)
        if seg_times is None:
            continue
        for seg_time in seg_times:
            if seg_time <= 0:
                continue
            t += seg_time
            d += seg_distance
            times.append(t)
            dists.append(d)
            speeds.append(seg_distance / seg_time * 3.6)
    if len(times) < 2:
        return None
    return np.asarray(times), np.asarray(dists), np.asarray(speeds)


def build_race_frames(sheet, circuit, classification=None, riders=None,
                      fps: int = 25, session_type: str = "R") -> Dict:
    """Build a replay ``frames`` dictionary from an Analysis sheet.

    Args:
        sheet: Parsed :class:`~src.motogp.timing_pdf.AnalysisSheet`.
        circuit: :class:`~src.motogp.geometry.CircuitGeometry` for the track.
        classification: Optional classification rows, used for total laps.
        riders: Optional ``{number: Rider}`` map for colours and names.
        fps: Output frame rate.
        session_type: Session code carried through to the renderer.
    """
    length_m = circuit.length_m
    line = circuit.track_line
    riders = riders or {}

    timelines = {}
    rider_tyre = {}
    for rider in sheet.riders:
        if rider.number is None:
            continue
        timeline = _rider_timeline(rider, length_m)
        if timeline is not None:
            timelines[rider.number] = (rider, timeline)
            # Riders run one tyre set over a race, so the rear compound is the
            # tyre and its age is simply how many laps have been run on it.
            rider_tyre[rider.number] = _compound_int(rider.rear_tyre)

    if not timelines:
        return {"frames": [], "driver_colors": {}, "track_statuses": [],
                "race_control_messages": [], "total_laps": None,
                "session_type": session_type, "max_tyre_life": {}}

    t_max = max(tl[0][-1] for _, tl in timelines.values())
    total_laps = max(len(rider.laps) for rider, _ in timelines.values())
    if classification:
        official = [r.total_laps for r in classification if r.total_laps]
        if official:
            total_laps = max(official)

    driver_colors = {}
    for number, (rider, _) in timelines.items():
        code = str(number)
        meta = riders.get(number)
        colour = meta.color if meta else None
        driver_colors[code] = _hex_to_rgb(colour)

    dt = 1.0 / fps
    n_frames = int(round(t_max / dt)) + 1
    frames: List[Dict] = []

    for i in range(n_frames):
        t = i * dt
        snapshot = {}
        for number, (rider, (times, dists, speeds)) in timelines.items():
            code = str(number)
            finished = t >= times[-1]
            distance = float(np.interp(t, times, dists))
            speed = 0.0 if finished else float(np.interp(t, times, speeds))
            progress = distance / length_m
            lap = min(int(distance // length_m) + 1, total_laps)
            x, y = line.point_at(distance % length_m)
            snapshot[code] = {
                "x": x, "y": y, "dist": distance,
                "lap": lap, "rel_dist": round((distance % length_m) / length_m, 4),
                "progress": round(progress, 6),
                "tyre": rider_tyre.get(number, -1),
                "tyre_life": float(max(lap - 1, 0)),
                "position": 0,
                "speed": speed, "gear": 0, "drs": 0,
                "throttle": 0.0, "brake": 0.0,
                "in_pit": False, "pit_stops": 0,
                "retired": bool(finished and progress < total_laps - 0.001),
            }

        # Rank the field by race progress; more laps covered is further ahead.
        for rank, code in enumerate(sorted(
                snapshot, key=lambda c: snapshot[c]["progress"], reverse=True), 1):
            snapshot[code]["position"] = rank

        leader_lap = max((c["lap"] for c in snapshot.values()), default=0)
        frames.append({"t": round(t, 3), "lap": leader_lap, "drivers": snapshot})

    return {
        "frames": frames,
        "driver_colors": driver_colors,
        "track_statuses": [],
        "race_control_messages": [],
        "total_laps": total_laps,
        "session_type": session_type,
        "max_tyre_life": {},
    }
