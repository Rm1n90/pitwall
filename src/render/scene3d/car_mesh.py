"""A low-poly car, built from boxes.

Recognisable from the angles the camera actually looks from, and cheap
enough that the whole field is one draw call. The car points down -Z, which
is the heading the instance shader rotates from.

Dimensions are roughly a real car in metres: 5.6 long, 2.0 wide, 0.95 tall.
The renderer scales them up, because a car drawn to scale on a circuit a
kilometre across is a couple of pixels.
"""

import numpy as np

CAR_LENGTH_M = 5.6
CAR_WIDTH_M = 2.0
CAR_HEIGHT_M = 0.95


def _box(centre, size):
    """Vertices, normals and indices for an axis-aligned box."""
    cx, cy, cz = centre
    sx, sy, sz = np.asarray(size, dtype=float) / 2.0

    # Each face gets its own four vertices so the normals stay sharp.
    faces = (
        ((0, 0, 1), ((-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz))),
        ((0, 0, -1), ((sx, -sy, -sz), (-sx, -sy, -sz), (-sx, sy, -sz), (sx, sy, -sz))),
        ((1, 0, 0), ((sx, -sy, sz), (sx, -sy, -sz), (sx, sy, -sz), (sx, sy, sz))),
        ((-1, 0, 0), ((-sx, -sy, -sz), (-sx, -sy, sz), (-sx, sy, sz), (-sx, sy, -sz))),
        ((0, 1, 0), ((-sx, sy, sz), (sx, sy, sz), (sx, sy, -sz), (-sx, sy, -sz))),
        ((0, -1, 0), ((-sx, -sy, -sz), (sx, -sy, -sz), (sx, -sy, sz), (-sx, -sy, sz))),
    )

    vertices, normals, indices = [], [], []
    for normal, corners in faces:
        base = len(vertices)
        for corner in corners:
            vertices.append((corner[0] + cx, corner[1] + cy, corner[2] + cz))
            normals.append(normal)
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

    return (np.array(vertices, dtype=float),
            np.array(normals, dtype=float),
            np.array(indices, dtype=np.uint32))


def build():
    """Return ``(vertices, normals, indices)`` for one car.

    The car is centred on the origin at ground level, so an instance can be
    placed by adding the point on the track it sits at.
    """
    parts = [
        # Survival cell and engine cover, the bulk of the car.
        _box((0.0, 0.34, 0.2), (1.05, 0.52, 3.4)),
        # The nose, narrower and lower, reaching forward.
        _box((0.0, 0.22, -2.1), (0.42, 0.3, 1.6)),
        # Front wing, wide and flat.
        _box((0.0, 0.1, -2.7), (CAR_WIDTH_M, 0.1, 0.5)),
        # Rear wing, raised on the centreline.
        _box((0.0, 0.78, 2.4), (1.5, 0.34, 0.16)),
        # Sidepods either side of the cockpit.
        _box((0.72, 0.28, 0.4), (0.5, 0.42, 2.0)),
        _box((-0.72, 0.28, 0.4), (0.5, 0.42, 2.0)),
        # Wheels, as blocks: at this size nobody counts the sides.
        _box((0.86, 0.33, -1.7), (0.36, 0.66, 0.72)),
        _box((-0.86, 0.33, -1.7), (0.36, 0.66, 0.72)),
        _box((0.9, 0.36, 1.7), (0.4, 0.72, 0.8)),
        _box((-0.9, 0.36, 1.7), (0.4, 0.72, 0.8)),
    ]

    vertices, normals, indices = [], [], []
    offset = 0
    for part_vertices, part_normals, part_indices in parts:
        vertices.append(part_vertices)
        normals.append(part_normals)
        indices.append(part_indices + offset)
        offset += len(part_vertices)

    return (np.vstack(vertices),
            np.vstack(normals),
            np.concatenate(indices).astype(np.uint32))


def interleaved():
    """The car as one buffer of position and normal, ready to upload."""
    vertices, normals, indices = build()
    data = np.empty((len(vertices), 6), dtype=np.float32)
    data[:, 0:3] = vertices
    data[:, 3:6] = normals
    return data.tobytes(), indices
