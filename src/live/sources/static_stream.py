"""Live data source backed by F1's public static timing archive.

During a session, F1 continuously appends to ``<topic>.jsonStream`` files
under ``https://livetiming.formula1.com/static/<session path>/``. Those files
are served by CloudFront without any authentication, which makes this the
source that works for everyone, including car positions and telemetry.

The tail of each file is fetched with HTTP range requests so only new bytes
are transferred; a typical poll costs a few kilobytes.
"""

import json
from typing import Dict, Optional
from urllib.parse import urljoin

import requests

from src.live.decoding import (
    LiveMessage,
    iter_stream_lines,
    normalise_topic,
    split_trailing_partial,
)
from src.live.sources.base import LiveDataSource, SourceStatus

STATIC_BASE_URL = "https://livetiming.formula1.com/static/"

# Topics that are only useful as a keyframe (they are tiny and rarely change)
# are still polled, because a red flag or a driver change must show up live.
DEFAULT_STATIC_TOPICS = (
    "SessionInfo",
    "DriverList",
    "TrackStatus",
    "SessionStatus",
    "LapCount",
    "WeatherData",
    "RaceControlMessages",
    "TimingAppData",
    "TimingData",
    "Position.z",
    "CarData.z",
)

# Feeds where only the newest state matters. Their keyframe is fetched once at
# startup so a mid-session join immediately has a full picture.
KEYFRAME_TOPICS = (
    "SessionInfo",
    "DriverList",
    "TrackStatus",
    "SessionStatus",
    "LapCount",
    "WeatherData",
    "TimingAppData",
    "TimingData",
    "RaceControlMessages",
)

REQUEST_TIMEOUT = 15


class _TopicCursor:
    """Tracks how much of one feed file has already been consumed."""

    def __init__(self, topic: str, url: str):
        self.topic = topic
        self.url = url
        self.offset = 0
        self.partial = ""
        self.errors = 0


class StaticStreamSource(LiveDataSource):
    """Polls the tail of the public ``.jsonStream`` feed files.

    Args:
        session_path: Session path such as
            ``'2026/2026-08-23_Dutch_Grand_Prix/2026-08-23_Race/'``.
        topics: Topics to follow. Defaults to everything the replay needs.
        poll_interval_s: Delay between polling rounds.
        start_at_end: When true (the default for a live session) only new data
            is streamed. Set to false to replay a session from its beginning.
        session: Optional pre-created :class:`requests.Session`.
    """

    name = "static"

    def __init__(
        self,
        session_path: str,
        topics=DEFAULT_STATIC_TOPICS,
        poll_interval_s: float = 2.0,
        start_at_end: bool = True,
        session: Optional[requests.Session] = None,
    ):
        super().__init__()
        if not session_path:
            raise ValueError("session_path is required for the static source")
        self.session_path = session_path if session_path.endswith("/") \
            else session_path + "/"
        self.topics = tuple(topics)
        self.poll_interval_s = max(0.5, float(poll_interval_s))
        self.start_at_end = start_at_end
        self._http = session or requests.Session()
        self._cursors: Dict[str, _TopicCursor] = {}

    @property
    def base_url(self) -> str:
        return urljoin(STATIC_BASE_URL, self.session_path)

    def _feed_url(self, topic: str, extension: str) -> str:
        return f"{self.base_url}{topic}.{extension}"

    def _fetch_keyframes(self) -> None:
        """Load the current state of the slow-moving feeds once at startup."""
        for topic in self.topics:
            if self._stop_event.is_set():
                return
            if topic not in KEYFRAME_TOPICS:
                continue
            url = self._feed_url(topic, "json")
            try:
                response = self._http.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                print(f"[live:static] keyframe {topic} unavailable: {exc}")
                continue
            if response.status_code != 200:
                continue
            try:
                data = response.content.decode("utf-8-sig")
                self.emit(LiveMessage(normalise_topic(topic),
                                      json.loads(data), ""))
            except ValueError:
                print(f"[live:static] could not decode keyframe for {topic}")

    def _prime_cursors(self) -> None:
        """Create a cursor per topic, optionally skipping existing content."""
        for topic in self.topics:
            cursor = _TopicCursor(topic, self._feed_url(topic, "jsonStream"))
            if self.start_at_end:
                cursor.offset = self._content_length(cursor.url)
            self._cursors[topic] = cursor

    def _content_length(self, url: str) -> int:
        try:
            response = self._http.head(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            return 0
        if response.status_code != 200:
            return 0
        try:
            return int(response.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return 0

    def _poll_topic(self, cursor: _TopicCursor) -> int:
        """Fetch and emit any new content for one topic. Returns bytes read."""
        headers = {
            "Range": f"bytes={cursor.offset}-",
            "Cache-Control": "no-cache",
        }
        try:
            response = self._http.get(
                cursor.url, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            cursor.errors += 1
            if cursor.errors in (1, 10):
                print(f"[live:static] {cursor.topic} request failed: {exc}")
            return 0

        # 416 simply means "no bytes past our cursor yet".
        if response.status_code in (416, 404):
            return 0
        if response.status_code not in (200, 206):
            cursor.errors += 1
            return 0

        if response.status_code == 200 and cursor.offset > 0:
            # The server ignored the range header; skip what we already have.
            content = response.content[cursor.offset:]
        else:
            content = response.content

        if not content:
            return 0

        cursor.errors = 0
        cursor.offset += len(content)

        text = cursor.partial + content.decode("utf-8-sig", errors="replace")
        complete, cursor.partial = split_trailing_partial(text)
        for message in iter_stream_lines(cursor.topic, complete):
            self.emit(message)
        return len(content)

    def _run(self) -> None:
        self._fetch_keyframes()
        self._prime_cursors()
        self._set_status(SourceStatus.CONNECTED)

        idle_rounds = 0
        while not self._stop_event.is_set():
            round_bytes = 0
            for cursor in self._cursors.values():
                if self._stop_event.is_set():
                    break
                round_bytes += self._poll_topic(cursor)

            if round_bytes:
                idle_rounds = 0
                self._set_status(SourceStatus.CONNECTED)
            else:
                idle_rounds += 1
                # ~1 minute without a single new byte means the session is
                # over or has not started yet.
                if idle_rounds * self.poll_interval_s > 60:
                    self._set_status(
                        SourceStatus.DEGRADED, "no new data from static feed"
                    )

            self._stop_event.wait(self.poll_interval_s)
