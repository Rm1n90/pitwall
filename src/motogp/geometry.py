"""Circuit geometry for MotoGP, built from the official circuit SVG.

MotoGP publishes a stroked outline of every circuit as an SVG. The longest path
in that file is the track centreline. This module flattens that path to a
polyline, scales it so its arc length matches the official lap length in metres,
and packages it as the same ``example_lap`` table the replay window already
draws F1 circuits from, plus a :class:`~src.lib.track_geometry.TrackLine` for
placing bikes by distance along the lap.
"""

import re
from dataclasses import dataclass

import numpy as np

# How many straight segments each Bezier curve is flattened into. Corners in
# these SVGs are a few curves each, so 16 keeps them smooth without bloating
# the point count.
_BEZIER_STEPS = 16

_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUMBER.pattern)
_PATH_D = re.compile(r'\bd="([^"]+)"')


def _cubic(p0, p1, p2, p3, steps):
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = (mt**3 * p0[0] + 3 * mt**2 * t * p1[0]
             + 3 * mt * t**2 * p2[0] + t**3 * p3[0])
        y = (mt**3 * p0[1] + 3 * mt**2 * t * p1[1]
             + 3 * mt * t**2 * p2[1] + t**3 * p3[1])
        yield (x, y)


def _quadratic(p0, p1, p2, steps):
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
        y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
        yield (x, y)


def flatten_path(d: str, steps: int = _BEZIER_STEPS):
    """Flatten an SVG path ``d`` string into a list of ``(x, y)`` points.

    Supports the commands MotoGP circuit outlines use: moves, lines, horizontal
    and vertical lines, cubic and quadratic Beziers (absolute and relative,
    including the smooth ``S``/``T`` forms) and close. Arcs, which these files
    do not use for the track, fall back to a straight segment.
    """
    tokens = _TOKEN.findall(d)
    i = 0
    points = []
    cx = cy = 0.0
    start = (0.0, 0.0)
    command = None
    prev_ctrl = None  # last control point, for smooth S/T

    def num():
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        token = tokens[i]
        if re.match(r"[A-Za-z]", token):
            command = token
            i += 1
        # Determine the implied command for repeated coordinate sets.
        rel = command.islower()
        c = command.upper()

        if c == "M":
            x, y = num(), num()
            cx, cy = (cx + x, cy + y) if rel else (x, y)
            start = (cx, cy)
            points.append((cx, cy))
            command = "l" if rel else "L"  # subsequent pairs are line-tos
            prev_ctrl = None
        elif c == "L":
            x, y = num(), num()
            cx, cy = (cx + x, cy + y) if rel else (x, y)
            points.append((cx, cy))
            prev_ctrl = None
        elif c == "H":
            x = num()
            cx = cx + x if rel else x
            points.append((cx, cy))
            prev_ctrl = None
        elif c == "V":
            y = num()
            cy = cy + y if rel else y
            points.append((cx, cy))
            prev_ctrl = None
        elif c == "C":
            x1, y1, x2, y2, x, y = (num() for _ in range(6))
            p1 = (cx + x1, cy + y1) if rel else (x1, y1)
            p2 = (cx + x2, cy + y2) if rel else (x2, y2)
            p3 = (cx + x, cy + y) if rel else (x, y)
            points.extend(_cubic((cx, cy), p1, p2, p3, steps))
            prev_ctrl = p2
            cx, cy = p3
        elif c == "S":
            x2, y2, x, y = (num() for _ in range(4))
            p2 = (cx + x2, cy + y2) if rel else (x2, y2)
            p3 = (cx + x, cy + y) if rel else (x, y)
            p1 = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]) if prev_ctrl else (cx, cy)
            points.extend(_cubic((cx, cy), p1, p2, p3, steps))
            prev_ctrl = p2
            cx, cy = p3
        elif c == "Q":
            x1, y1, x, y = (num() for _ in range(4))
            p1 = (cx + x1, cy + y1) if rel else (x1, y1)
            p2 = (cx + x, cy + y) if rel else (x, y)
            points.extend(_quadratic((cx, cy), p1, p2, steps))
            prev_ctrl = p1
            cx, cy = p2
        elif c == "T":
            x, y = num(), num()
            p2 = (cx + x, cy + y) if rel else (x, y)
            p1 = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]) if prev_ctrl else (cx, cy)
            points.extend(_quadratic((cx, cy), p1, p2, steps))
            prev_ctrl = p1
            cx, cy = p2
        elif c == "A":
            # Arc: not used for the track path; approximate by its endpoint.
            _rx, _ry, _rot, _laf, _sf, x, y = (num() for _ in range(7))
            cx, cy = (cx + x, cy + y) if rel else (x, y)
            points.append((cx, cy))
            prev_ctrl = None
        elif c == "Z":
            points.append(start)
            cx, cy = start
            prev_ctrl = None
        else:
            i += 1  # unknown token, skip defensively
    return points


def _longest_path(svg_text: str):
    best = ""
    for match in _PATH_D.finditer(svg_text):
        d = match.group(1)
        if len(d) > len(best):
            best = d
    if not best:
        raise ValueError("no <path d=...> found in SVG")
    return best


def _dedupe(points):
    out = []
    for p in points:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


@dataclass
class CircuitGeometry:
    """A circuit ready to draw and to place riders on.

    Attributes:
        example_lap: Table with ``X``/``Y``/``Z``/``Distance``/
            ``RelativeDistance``/``DRS``/``Speed`` columns, in metres.
        track_line: Centreline supporting distance/coordinate lookup.
        length_m: Official lap length in metres.
        rotation: Display rotation in degrees (0 for SVG-derived geometry).
    """
    example_lap: object
    track_line: object
    length_m: float
    rotation: float = 0.0
    pit_lane: list = None  # world-coordinate (x, y) points, or None


def circuit_from_svg(path: str, length_m: float) -> CircuitGeometry:
    """Build circuit geometry from an SVG file scaled to ``length_m`` metres."""
    with open(path, "r", encoding="utf-8") as handle:
        svg_text = handle.read()
    return circuit_from_svg_text(svg_text, length_m)


_RECT = re.compile(r'<rect\b([^>]*)>')
_ATTR = re.compile(r'(\w+)="([^"]+)"')


def _stroked_path_ds(svg_text: str):
    """Return the ``d`` strings of stroked, fill:none paths, longest first.

    The track is the longest such path; the pit lane is the next longest.
    Identifying them this way survives the class names differing between
    circuits.
    """
    stroked = {c for c in re.findall(r'\.(st\d+)\s*\{[^}]*stroke:', svg_text)}
    ds = []
    for m in re.finditer(r'<path\b[^>]*>', svg_text):
        tag = m.group(0)
        cls = re.search(r'class="(st\d+)"', tag)
        d = re.search(r'\bd="([^"]+)"', tag)
        if d and cls and cls.group(1) in stroked:
            ds.append(d.group(1))
    ds.sort(key=len, reverse=True)
    return ds


def _start_finish_svg(svg_text):
    """Find the start/finish line as the centroid of the checkered-flag squares.

    The flag is drawn as a tight cluster of small (~4-5px) squares. Their
    centroid marks the line; returns ``None`` if no such cluster is found so the
    caller can fall back to the path start.
    """
    centres = []
    for m in _RECT.finditer(svg_text):
        attrs = dict(_ATTR.findall(m.group(1)))
        try:
            w = float(attrs.get("width", 0)); h = float(attrs.get("height", 0))
            x = float(attrs.get("x", 0)); y = float(attrs.get("y", 0))
        except ValueError:
            continue
        if 2.0 < w < 9.0 and 2.0 < h < 9.0:
            centres.append((x + w / 2, y + h / 2))
    if len(centres) < 4:
        return None
    pts = np.asarray(centres)
    # Pick the densest cluster: the point with the most neighbours within 40px,
    # then average that neighbourhood. This ignores stray small rects elsewhere.
    best_i, best_n = 0, -1
    for i, p in enumerate(pts):
        n = int(np.sum(np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1]) < 40))
        if n > best_n:
            best_i, best_n = i, n
    near = pts[np.hypot(pts[:, 0] - pts[best_i, 0],
                        pts[:, 1] - pts[best_i, 1]) < 40]
    return (float(near[:, 0].mean()), float(near[:, 1].mean()))


def circuit_from_svg_text(svg_text: str, length_m: float) -> CircuitGeometry:
    """Build circuit geometry from raw SVG markup.

    Extracts the track (longest stroked path), the pit lane (next longest) and
    the start/finish line, scaling them together so they align.
    """
    ds = _stroked_path_ds(svg_text)
    track_d = ds[0] if ds else _longest_path(svg_text)
    pit_d = ds[1] if len(ds) > 1 else None
    sf_svg = _start_finish_svg(svg_text)
    return circuit_from_path(track_d, length_m, pit_d=pit_d, sf_svg=sf_svg)


def circuit_from_path(d: str, length_m: float, pit_d=None,
                      sf_svg=None) -> CircuitGeometry:
    """Build circuit geometry from a track path ``d``.

    ``pit_d`` and ``sf_svg`` are optional pit-lane path and start/finish point
    in the same SVG coordinate space, scaled and flipped identically.
    """
    import pandas as pd

    from src.lib.track_geometry import TrackLine

    points = _dedupe(flatten_path(d))
    xy = np.asarray(points, dtype=float)
    # SVG y grows downward; flip it so the map is the right way up.
    xy[:, 1] = -xy[:, 1]

    steps = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    raw_length = float(steps.sum())
    if raw_length <= 0:
        raise ValueError("degenerate circuit path")

    scale = length_m / raw_length
    xy *= scale

    # Rotate the loop so index 0 sits at the real start/finish line, which is
    # where the replay draws the line and where riders begin.
    if sf_svg is not None:
        sf = np.array([sf_svg[0], -sf_svg[1]]) * scale
        closed = np.hypot(xy[0, 0] - xy[-1, 0], xy[0, 1] - xy[-1, 1]) < 1e-6
        core = xy[:-1] if closed else xy
        i = int(np.argmin(np.hypot(core[:, 0] - sf[0], core[:, 1] - sf[1])))
        xy = np.roll(core, -i, axis=0)

    distance = np.concatenate(([0.0], np.cumsum(np.hypot(
        np.diff(xy[:, 0]), np.diff(xy[:, 1])))))

    pit_lane = None
    if pit_d:
        pit = np.asarray(_dedupe(flatten_path(pit_d)), dtype=float)
        if len(pit) >= 2:
            pit[:, 1] = -pit[:, 1]
            pit *= scale
            pit_lane = [(float(px), float(py)) for px, py in pit]

    example_lap = pd.DataFrame({
        "X": xy[:, 0],
        "Y": xy[:, 1],
        "Z": np.zeros(len(xy)),
        "Distance": distance,
        "RelativeDistance": distance / distance[-1],
        "DRS": np.zeros(len(xy), dtype=int),
        "Speed": np.zeros(len(xy)),
    })
    track_line = TrackLine(xy[:, 0], xy[:, 1])
    return CircuitGeometry(example_lap=example_lap, track_line=track_line,
                           pit_lane=pit_lane,
                           length_m=length_m)
