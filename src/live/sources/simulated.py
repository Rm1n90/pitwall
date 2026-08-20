"""A source that replays a finished session as if it were happening now.

This exists so live mode can be developed, demonstrated and tested outside a
race weekend, and so a user can rehearse their setup before lights out. It
downloads a past session's public feed archive, caches it, and then emits the
recorded messages paced by their original timestamps.
"""

import os
import time
from typing import List, Optional, Tuple

import requests

from src.live.decoding import (
    LiveMessage,
    parse_stream_line,
    parse_stream_time,
    split_feed_lines,
)
from src.live.sources.base import LiveDataSource, SourceStatus
from src.live.sources.static_stream import (
    DEFAULT_STATIC_TOPICS,
    REQUEST_TIMEOUT,
    STATIC_BASE_URL,
)

CACHE_DIR_NAME = "live_archive"


class SimulatedLiveSource(LiveDataSource):
    """Replays an archived session at (a multiple of) real time.

    Args:
        session_path: Feed path of the session to replay.
        topics: Topics to include in the replay.
        speed: Wall-clock multiplier. ``1.0`` matches the original pace.
        start_offset_s: Skip this many seconds of the recording before
            starting, which is handy for jumping straight to the race start.
        cache_dir: Directory used to cache the downloaded feed files.
    """

    name = "simulated"

    def __init__(
        self,
        session_path: str,
        topics=DEFAULT_STATIC_TOPICS,
        speed: float = 1.0,
        start_offset_s: float = 0.0,
        cache_dir: str = "computed_data",
        session: Optional[requests.Session] = None,
    ):
        super().__init__()
        if not session_path:
            raise ValueError("session_path is required for the simulated source")
        self.session_path = session_path if session_path.endswith("/") \
            else session_path + "/"
        self.topics = tuple(topics)
        self.speed = max(0.1, float(speed))
        self.start_offset_s = max(0.0, float(start_offset_s))
        self.cache_dir = os.path.join(cache_dir, CACHE_DIR_NAME,
                                      self.session_path.strip("/"))
        self._http = session or requests.Session()
        #: Total length of the recording in seconds, filled in once loaded.
        self.duration_s = 0.0

    def _cached_path(self, topic: str) -> str:
        return os.path.join(self.cache_dir, f"{topic}.jsonStream")

    def _download_topic(self, topic: str) -> Optional[str]:
        """Return the feed file for ``topic``, downloading it if needed."""
        cached = self._cached_path(topic)
        if os.path.exists(cached) and os.path.getsize(cached) > 0:
            # newline='' is essential here: universal newline translation
            # would rewrite the feed's \r\n separators and break parsing.
            with open(cached, "r", encoding="utf-8",
                      errors="replace", newline="") as handle:
                return handle.read()

        url = f"{STATIC_BASE_URL}{self.session_path}{topic}.jsonStream"
        try:
            response = self._http.get(url, timeout=REQUEST_TIMEOUT * 4)
        except requests.RequestException as exc:
            print(f"[live:simulated] could not download {topic}: {exc}")
            return None
        if response.status_code != 200:
            print(f"[live:simulated] {topic} unavailable "
                  f"(HTTP {response.status_code})")
            return None

        text = response.content.decode("utf-8-sig", errors="replace")
        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            with open(cached, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        except OSError as exc:
            print(f"[live:simulated] could not cache {topic}: {exc}")
        return text

    def _load_timeline(self) -> List[Tuple[float, LiveMessage]]:
        """Load every topic and merge it into one time-ordered timeline."""
        timeline: List[Tuple[float, LiveMessage]] = []
        for topic in self.topics:
            if self._stop_event.is_set():
                break
            text = self._download_topic(topic)
            if not text:
                continue
            for line in split_feed_lines(text):
                message = parse_stream_line(topic, line)
                if message is None:
                    continue
                offset = parse_stream_time(message.stream_time)
                if offset is None:
                    continue
                timeline.append((offset.total_seconds(), message))
        timeline.sort(key=lambda item: item[0])
        return timeline

    def _run(self) -> None:
        print(f"[live:simulated] loading archive for {self.session_path}")
        timeline = self._load_timeline()
        if not timeline:
            self._set_status(SourceStatus.FAILED, "no archived data found")
            print("[live:simulated] no archived data found for this session")
            return

        self.duration_s = timeline[-1][0] - timeline[0][0]
        base_time = timeline[0][0] + self.start_offset_s
        print(f"[live:simulated] replaying {len(timeline)} messages "
              f"({self.duration_s / 60:.0f} min) at {self.speed}x")
        self._set_status(SourceStatus.CONNECTED)

        wall_start = time.monotonic()
        for offset, message in timeline:
            if self._stop_event.is_set():
                return
            if offset < base_time:
                # Everything before the start point is replayed immediately so
                # the session state is complete when playback begins.
                self.emit(message)
                continue
            target = (offset - base_time) / self.speed
            delay = target - (time.monotonic() - wall_start)
            if delay > 0:
                if self._stop_event.wait(delay):
                    return
            self.emit(message)

        self._set_status(SourceStatus.DEGRADED, "archive replay finished")
        print("[live:simulated] replay finished")
