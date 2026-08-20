"""A growing, memory-bounded frame list for live sessions.

The replay window treats its frame data as a plain list: it takes ``len()``
and indexes into it. This buffer keeps that contract while frames are still
arriving, and trims the oldest ones once a session runs long, without
invalidating the indices the window is already holding.
"""

import threading
from typing import Iterator, List, Optional, Sequence

from src.live.config import DEFAULT_MAX_FRAMES

# Frames are dropped in blocks so trimming does not run on every append.
TRIM_BLOCK = 5_000


class LiveFrameBuffer(Sequence):
    """Append-only frame sequence with absolute indexing.

    Indices are absolute for the whole session: after older frames have been
    trimmed, ``buffer[0]`` returns the oldest frame that is still retained
    rather than raising, so a viewer that was rewound far back simply stops at
    the start of the retained window.

    Args:
        max_frames: Maximum number of frames kept in memory.
    """

    def __init__(self, max_frames: int = DEFAULT_MAX_FRAMES):
        self._frames: List[dict] = []
        self._offset = 0
        self._max_frames = max(1, int(max_frames))
        # Trim in blocks so the cost is amortised, but never larger than a
        # quarter of the retained window (keeps small buffers well behaved).
        self._trim_block = max(1, min(TRIM_BLOCK, self._max_frames // 4))
        self._lock = threading.RLock()

    def append(self, frame: dict) -> int:
        """Append a frame and return its absolute index."""
        with self._lock:
            self._frames.append(frame)
            index = self._offset + len(self._frames) - 1
            if len(self._frames) > self._max_frames + self._trim_block:
                drop = len(self._frames) - self._max_frames
                del self._frames[:drop]
                self._offset += drop
            return index

    def extend(self, frames) -> None:
        for frame in frames:
            self.append(frame)

    @property
    def offset(self) -> int:
        """Absolute index of the oldest retained frame."""
        with self._lock:
            return self._offset

    @property
    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._frames[-1] if self._frames else None

    @property
    def latest_index(self) -> int:
        """Absolute index of the newest frame, or ``-1`` when empty."""
        with self._lock:
            if not self._frames:
                return -1
            return self._offset + len(self._frames) - 1

    def __len__(self) -> int:
        with self._lock:
            return self._offset + len(self._frames)

    def __getitem__(self, index):
        with self._lock:
            if isinstance(index, slice):
                start, stop, step = index.indices(
                    self._offset + len(self._frames)
                )
                return [
                    self._frames[max(0, i - self._offset)]
                    for i in range(start, stop, step)
                    if self._frames
                ]
            if not self._frames:
                raise IndexError("live frame buffer is empty")
            if index < 0:
                index += self._offset + len(self._frames)
            local = index - self._offset
            # Clamp instead of raising: the window may still hold an index
            # that has since been trimmed away.
            local = min(max(local, 0), len(self._frames) - 1)
            return self._frames[local]

    def __iter__(self) -> Iterator[dict]:
        with self._lock:
            return iter(list(self._frames))

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._frames)
