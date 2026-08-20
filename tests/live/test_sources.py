"""Tests for the live data sources."""

import json
import threading

import pytest

from src.live.sources.base import LiveDataSource, SourceStatus
from src.live.sources.static_stream import StaticStreamSource


class _Response:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _FakeHttp:
    """Serves a growing feed file, like the real archive does during a session."""

    def __init__(self, bodies=None, keyframes=None):
        self.bodies = bodies or {}
        self.keyframes = keyframes or {}
        self.requests = []

    def head(self, url, **kwargs):
        body = self._body_for(url)
        return _Response(headers={"Content-Length": str(len(body))})

    def get(self, url, headers=None, **kwargs):
        self.requests.append((url, (headers or {}).get("Range")))
        if url.endswith(".json"):
            payload = self.keyframes.get(url.rsplit("/", 1)[-1])
            if payload is None:
                return _Response(status_code=404)
            return _Response(json.dumps(payload).encode("utf-8-sig"))

        body = self._body_for(url)
        start = 0
        if headers and headers.get("Range"):
            start = int(headers["Range"].split("=")[1].split("-")[0])
        if start >= len(body):
            return _Response(status_code=416)
        return _Response(body[start:], status_code=206)

    def _body_for(self, url):
        return self.bodies.get(url.rsplit("/", 1)[-1], b"")


class _CollectingSource(LiveDataSource):
    name = "test"

    def __init__(self):
        super().__init__()
        self.ran = threading.Event()

    def _run(self):
        self._set_status(SourceStatus.CONNECTED)
        self.emit(None)  # must be ignored
        self.ran.set()


class TestSourceBase:
    def test_reports_its_lifecycle(self):
        source = _CollectingSource()
        assert source.status == SourceStatus.IDLE

        received = []
        source.start(received.append)
        source.ran.wait(timeout=2)
        source.stop()

        assert source.status == SourceStatus.STOPPED
        assert received == []

    def test_a_failing_handler_does_not_kill_the_source(self):
        source = _CollectingSource()

        def _boom(_message):
            raise RuntimeError("handler exploded")

        source._handler = _boom
        from src.live.decoding import LiveMessage
        source.emit(LiveMessage("TrackStatus", {}))  # must not raise

    def test_a_failing_run_is_reported_not_raised(self):
        class _Broken(LiveDataSource):
            name = "broken"

            def _run(self):
                raise RuntimeError("no network")

        source = _Broken()
        source.start(lambda _m: None)
        source._thread.join(timeout=2)

        assert source.status == SourceStatus.FAILED
        assert "no network" in source.last_error


class TestStaticStreamSource:
    def test_requires_a_session_path(self):
        with pytest.raises(ValueError):
            StaticStreamSource(session_path="")

    def test_normalises_the_session_path(self):
        source = StaticStreamSource(session_path="2026/a/b")
        assert source.session_path.endswith("/")
        assert source.base_url.endswith("2026/a/b/")

    def test_reads_keyframes_before_streaming(self):
        http = _FakeHttp(keyframes={"TrackStatus.json": {"Status": "2"}})
        source = StaticStreamSource("2026/a/b/", topics=("TrackStatus",),
                                    session=http)
        received = []
        source._handler = received.append
        source._fetch_keyframes()

        assert received[0].topic == "TrackStatus"
        assert received[0].data == {"Status": "2"}

    def test_streams_only_new_bytes(self):
        body = (b'00:00:01.000{"Status":"2"}\r\n'
                b'00:00:02.000{"Status":"1"}\r\n')
        http = _FakeHttp(bodies={"TrackStatus.jsonStream": body})
        source = StaticStreamSource("2026/a/b/", topics=("TrackStatus",),
                                    start_at_end=False, session=http)
        received = []
        source._handler = received.append
        source._prime_cursors()

        assert source._poll_topic(source._cursors["TrackStatus"]) == len(body)
        assert [m.data["Status"] for m in received] == ["2", "1"]

        # A second poll has nothing new to return.
        assert source._poll_topic(source._cursors["TrackStatus"]) == 0
        assert len(received) == 2

    def test_carries_a_half_written_line_to_the_next_poll(self):
        http = _FakeHttp(bodies={"TrackStatus.jsonStream":
                                 b'00:00:01.000{"Status":"2"}\r\n00:00:02.0'})
        source = StaticStreamSource("2026/a/b/", topics=("TrackStatus",),
                                    start_at_end=False, session=http)
        received = []
        source._handler = received.append
        source._prime_cursors()
        source._poll_topic(source._cursors["TrackStatus"])

        assert len(received) == 1
        assert source._cursors["TrackStatus"].partial == '00:00:02.0'

    def test_starts_at_the_end_for_a_live_join(self):
        body = b'00:00:01.000{"Status":"2"}\r\n'
        http = _FakeHttp(bodies={"TrackStatus.jsonStream": body})
        source = StaticStreamSource("2026/a/b/", topics=("TrackStatus",),
                                    start_at_end=True, session=http)
        received = []
        source._handler = received.append
        source._prime_cursors()
        source._poll_topic(source._cursors["TrackStatus"])

        assert received == []

    def test_a_missing_feed_is_not_an_error(self):
        source = StaticStreamSource("2026/a/b/", topics=("TrackStatus",),
                                    start_at_end=False, session=_FakeHttp())
        source._handler = lambda _m: None
        source._prime_cursors()

        assert source._poll_topic(source._cursors["TrackStatus"]) == 0
