"""The camera for the 3D circuit view.

World space is Y-up: X and Z are the ground plane and Y is elevation. The
position feed gives X and Y on the ground with Z as altitude, so the mesh
builder swaps the last two; everything from here up works in Y-up.

The camera orbits a target rather than flying freely. A circuit is a thing
you look at from outside, and an orbit is far easier to control than six
degrees of freedom.
"""

import numpy as np

#: Keep the camera above the ground and short of straight overhead. Looking
#: exactly down the up-axis makes the view matrix degenerate.
MIN_PITCH = np.deg2rad(4.0)
MAX_PITCH = np.deg2rad(86.0)

DEFAULT_FOV = np.deg2rad(48.0)
DEFAULT_NEAR = 1.0
DEFAULT_FAR = 20000.0


class Camera3D:
    """An orbit camera, and the projection that goes with it."""

    def __init__(self, target=(0.0, 0.0, 0.0), distance: float = 1200.0,
                 yaw: float = 0.0, pitch: float = np.deg2rad(35.0),
                 fov: float = DEFAULT_FOV,
                 near: float = DEFAULT_NEAR, far: float = DEFAULT_FAR,
                 min_distance: float = 40.0, max_distance: float = 12000.0):
        self.target = np.asarray(target, dtype=float)
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(np.clip(pitch, MIN_PITCH, MAX_PITCH))
        self.fov = float(fov)
        self.near = float(near)
        self.far = float(far)
        self.min_distance = float(min_distance)
        self.max_distance = float(max_distance)

    # -- placement --------------------------------------------------------

    def position(self) -> np.ndarray:
        """Where the camera is, in world space."""
        horizontal = self.distance * np.cos(self.pitch)
        return self.target + np.array([
            horizontal * np.sin(self.yaw),
            self.distance * np.sin(self.pitch),
            horizontal * np.cos(self.yaw),
        ])

    def look_at(self, target) -> None:
        """Point the camera at a new place, keeping its angle and distance."""
        self.target = np.asarray(target, dtype=float)

    def orbit(self, delta_yaw: float, delta_pitch: float) -> None:
        """Swing around the target, staying above the ground."""
        self.yaw += float(delta_yaw)
        self.pitch = float(np.clip(self.pitch + float(delta_pitch),
                                   MIN_PITCH, MAX_PITCH))

    def fit(self, radius: float, aspect: float, margin: float = 1.15) -> None:
        """Stand far enough back that a circuit of ``radius`` fits the view.

        Both directions are checked. On a wide window the vertical field of
        view is the tighter of the two, and on a tall one it is the
        horizontal, so whichever needs more room decides.
        """
        half = np.tan(self.fov / 2.0)
        vertical = radius / max(half, 1e-6)
        horizontal = radius / max(half * max(aspect, 1e-6), 1e-6)
        self.distance = float(np.clip(max(vertical, horizontal) * margin,
                                      self.min_distance, self.max_distance))

    def frame_points(self, points, width: float, height: float,
                     margin: float = 1.06, rounds: int = 8,
                     fill=(1.0, 1.0)) -> None:
        """Pull back just far enough that every point is on screen.

        More exact than :meth:`fit`, which assumes the circuit is a sphere.
        A tilted view foreshortens the circuit, so fitting its bounding
        radius leaves a band of empty ground above and below it. Projection
        is not linear in distance, so this closes in over a few rounds
        rather than solving directly.

        ``fill`` is how much of the window the circuit may occupy on each
        axis. Panels cover the sides and the top, and a circuit drawn
        underneath them is a circuit nobody can see.
        """
        world = np.asarray(points, dtype=float).reshape(-1, 3)
        if not len(world):
            return

        for _ in range(int(rounds)):
            screen, _depth, visible = self.project(world, width, height)
            if not visible.any():
                self.distance = min(self.distance * 2.0, self.max_distance)
                continue

            on_screen = screen[visible]
            fill_x = max(float(fill[0]), 1e-3)
            fill_y = max(float(fill[1]), 1e-3)
            extent = max(
                np.abs(on_screen[:, 0] / width * 2.0 - 1.0).max() / fill_x,
                np.abs(on_screen[:, 1] / height * 2.0 - 1.0).max() / fill_y,
            )
            if extent < 1e-6:
                break

            wanted = float(np.clip(self.distance * extent * margin,
                                   self.min_distance, self.max_distance))
            if abs(wanted - self.distance) < 0.5:
                self.distance = wanted
                break
            self.distance = wanted

    def zoom(self, factor: float) -> None:
        """Move closer or further away, within useful limits."""
        self.distance = float(np.clip(self.distance * float(factor),
                                      self.min_distance, self.max_distance))

    # -- matrices ---------------------------------------------------------

    def view_matrix(self) -> np.ndarray:
        eye = self.position()
        forward = self.target - eye
        length = np.linalg.norm(forward)
        if length < 1e-9:
            forward = np.array([0.0, 0.0, -1.0])
        else:
            forward = forward / length

        world_up = np.array([0.0, 1.0, 0.0])
        right = np.cross(forward, world_up)
        right_length = np.linalg.norm(right)
        if right_length < 1e-9:
            # Looking straight up or down; any right vector will do.
            right = np.array([1.0, 0.0, 0.0])
        else:
            right = right / right_length
        up = np.cross(right, forward)

        view = np.eye(4)
        view[0, :3] = right
        view[1, :3] = up
        view[2, :3] = -forward
        view[0, 3] = -right.dot(eye)
        view[1, 3] = -up.dot(eye)
        view[2, 3] = forward.dot(eye)
        return view

    def projection_matrix(self, aspect: float) -> np.ndarray:
        aspect = max(float(aspect), 1e-6)
        scale = 1.0 / np.tan(self.fov / 2.0)
        near, far = self.near, self.far

        projection = np.zeros((4, 4))
        projection[0, 0] = scale / aspect
        projection[1, 1] = scale
        projection[2, 2] = (far + near) / (near - far)
        projection[2, 3] = (2.0 * far * near) / (near - far)
        projection[3, 2] = -1.0
        return projection

    def view_projection(self, aspect: float) -> np.ndarray:
        return self.projection_matrix(aspect) @ self.view_matrix()

    def view_projection_bytes(self, aspect: float) -> bytes:
        """The combined matrix laid out the way a shader expects it."""
        return np.ascontiguousarray(
            self.view_projection(aspect).T, dtype=np.float32).tobytes()

    # -- projection -------------------------------------------------------

    def project(self, points, width: float, height: float):
        """Project world points onto the screen.

        Args:
            points: ``(n, 3)`` world positions.
            width: Viewport width in pixels.
            height: Viewport height in pixels.

        Returns:
            ``(screen_xy, depth, visible)``. Screen coordinates count from
            the bottom left, the way the rest of the window does. Points
            behind the camera are marked not visible; their screen positions
            are meaningless rather than merely off-screen.
        """
        world = np.asarray(points, dtype=float).reshape(-1, 3)
        if not len(world):
            return (np.zeros((0, 2)), np.zeros(0), np.zeros(0, dtype=bool))

        homogeneous = np.column_stack([world, np.ones(len(world))])
        clip = homogeneous @ self.view_projection(width / max(height, 1e-6)).T

        w = clip[:, 3]
        visible = w > 1e-6
        safe_w = np.where(visible, w, 1.0)
        ndc = clip[:, :3] / safe_w[:, None]

        screen = np.column_stack([
            (ndc[:, 0] * 0.5 + 0.5) * width,
            (ndc[:, 1] * 0.5 + 0.5) * height,
        ])
        return screen, w, visible


#: How the camera follows the session.
MODE_FREE = "free"
MODE_CHASE = "chase"
MODE_TRACK = "track"
CAMERA_MODES = (MODE_FREE, MODE_CHASE, MODE_TRACK)

#: Chase camera: close behind the car and only slightly above it.
CHASE_DISTANCE_M = 46.0
CHASE_PITCH = np.deg2rad(15.0)

#: Tracking camera: further out and higher, like a camera on a gantry.
TRACK_DISTANCE_M = 130.0
TRACK_PITCH = np.deg2rad(26.0)

#: How quickly the camera catches up with the car it is following. A camera
#: pinned exactly to the car shakes with every jitter in the position feed.
FOLLOW_SMOOTHING = 0.12


def next_mode(mode: str) -> str:
    """The mode after this one, wrapping around."""
    try:
        return CAMERA_MODES[(CAMERA_MODES.index(mode) + 1) % len(CAMERA_MODES)]
    except ValueError:
        return MODE_FREE


def smooth_towards(current, target, factor: float = FOLLOW_SMOOTHING):
    """Move part of the way from one point to another."""
    current = np.asarray(current, dtype=float)
    target = np.asarray(target, dtype=float)
    return current + (target - current) * float(np.clip(factor, 0.0, 1.0))


def smooth_angle_towards(current: float, target: float,
                         factor: float = FOLLOW_SMOOTHING) -> float:
    """Move part of the way between two angles, the short way round.

    Following a car through the last corner of a lap must not send the
    camera the long way round when the heading crosses from pi to -pi.
    """
    difference = (float(target) - float(current) + np.pi) % (2 * np.pi) - np.pi
    return float(current) + difference * float(np.clip(factor, 0.0, 1.0))
