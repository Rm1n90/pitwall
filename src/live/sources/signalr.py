"""Live data source backed by F1's SignalR feed.

This is the lowest latency option: messages arrive as F1 publishes them,
typically ahead of the television broadcast.

Timing, track status, weather and race control are delivered to
unauthenticated clients. The car position and telemetry topics
(``Position.z`` / ``CarData.z``) require a Formula 1 account token, which is
obtained through FastF1's browser sign-in flow when available. When those
topics stay silent, :attr:`has_car_data` remains false so the engine can add
the public static feed alongside this one.
"""

import json
import logging
import threading
import time
from typing import Optional

import requests

from src.live.decoding import LiveMessage, decode_payload, normalise_topic
from src.live.sources.base import LiveDataSource, SourceStatus

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate"
CONNECTION_URL = "wss://livetiming.formula1.com/signalrcore"

# Topics that only arrive for authenticated subscribers.
CAR_TOPICS = ("Position", "CarData")

CONNECT_TIMEOUT_S = 30
RECONNECT_DELAY_S = 5


class SignalRSource(LiveDataSource):
    """Streams live timing messages over SignalR.

    Args:
        topics: Topics to subscribe to.
        no_auth: Never attempt to use a Formula 1 account token.
        record_path: Optional file to append the raw feed to. The format
            matches FastF1's recorder, so the file can later be replayed with
            :class:`fastf1.livetiming.data.LiveTimingData`.
    """

    name = "signalr"

    def __init__(self, topics, no_auth: bool = False,
                 record_path: Optional[str] = None):
        super().__init__()
        self.topics = list(topics)
        self.no_auth = no_auth
        self.record_path = record_path
        self._connection = None
        self._connected = threading.Event()
        self._record_file = None
        self._record_lock = threading.Lock()
        #: Set once a car position/telemetry message has been received.
        self.has_car_data = False
        self._t_last_message = 0.0

    def _build_headers(self) -> dict:
        """Pre-negotiate to pick up the load balancer cookie F1 expects."""
        headers = {}
        try:
            response = requests.options(NEGOTIATE_URL, timeout=CONNECT_TIMEOUT_S)
            cookie = response.cookies.get("AWSALBCORS")
            if cookie:
                headers["Cookie"] = f"AWSALBCORS={cookie}"
        except requests.RequestException as exc:
            print(f"[live:signalr] negotiate request failed: {exc}")
        return headers

    def _access_token_factory(self):
        """Return a callable yielding an F1 account token, or ``None``."""
        if self.no_auth:
            return None
        from src.live.auth import get_token_provider

        provider = get_token_provider()
        if provider is None:
            print("[live:signalr] no Formula 1 sign-in available, "
                  "connecting anonymously")
        return provider

    def _open_record_file(self) -> None:
        if not self.record_path:
            return
        try:
            self._record_file = open(self.record_path, "a", encoding="utf-8")
        except OSError as exc:
            print(f"[live:signalr] cannot record to {self.record_path}: {exc}")
            self._record_file = None

    def _record(self, raw) -> None:
        if self._record_file is None:
            return
        with self._record_lock:
            try:
                self._record_file.write(str(raw) + "\n")
                self._record_file.flush()
            except OSError:
                self._record_file = None

    def _handle_snapshot(self, result: dict) -> None:
        """Handle the keyframe returned when subscribing."""
        for topic, payload in (result or {}).items():
            self._record([topic, json.dumps(payload), ""])
            self._dispatch(topic, payload, "")

    def _handle_feed(self, message) -> None:
        """Handle a streamed ``[topic, payload, timestamp]`` message."""
        if not isinstance(message, (list, tuple)) or len(message) < 2:
            return
        topic = message[0]
        payload = message[1]
        stream_time = message[2] if len(message) > 2 else ""
        self._record(list(message))
        self._dispatch(topic, payload, stream_time)

    def _dispatch(self, topic: str, payload, stream_time: str) -> None:
        self._t_last_message = time.time()
        try:
            data = decode_payload(topic, payload)
        except Exception as exc:
            print(f"[live:signalr] could not decode {topic}: {exc}")
            return
        clean_topic = normalise_topic(topic)
        if clean_topic in CAR_TOPICS:
            self.has_car_data = True
        self.emit(LiveMessage(clean_topic, data, stream_time or ""))

    def _on_message(self, msg) -> None:
        # signalrcore hands us either the invocation result (the keyframe) or
        # a streamed argument list.
        result = getattr(msg, "result", None)
        if isinstance(result, dict):
            self._handle_snapshot(result)
        elif isinstance(msg, (list, tuple)):
            self._handle_feed(msg)

    def _connect_once(self) -> None:
        from signalrcore.hub_connection_builder import HubConnectionBuilder

        options = {"verify_ssl": True, "headers": self._build_headers()}
        token_factory = self._access_token_factory()
        # signalrcore rejects a None factory, so the key is only ever added
        # when a real callable is available.
        if token_factory is not None:
            options["access_token_factory"] = token_factory

        self._connected.clear()
        self._connection = (
            HubConnectionBuilder()
            .with_url(CONNECTION_URL, options=options)
            .configure_logging(logging.WARNING)
            .build()
        )
        self._connection.on_open(self._connected.set)
        self._connection.on_close(self._connected.clear)
        self._connection.on("feed", self._on_message)
        self._connection.start()

        if not self._connected.wait(timeout=CONNECT_TIMEOUT_S):
            raise TimeoutError("timed out waiting for the live timing stream")

        self._set_status(SourceStatus.CONNECTED)
        self._t_last_message = time.time()
        self._connection.send(
            "Subscribe", [self.topics], on_invocation=self._on_message
        )

    def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.stop()
        except Exception:
            pass

    def _run(self) -> None:
        self._open_record_file()
        while not self._stop_event.is_set():
            try:
                self._connect_once()
            except Exception as exc:
                self._set_status(SourceStatus.RECONNECTING, str(exc))
                print(f"[live:signalr] connection failed ({exc}); "
                      f"retrying in {RECONNECT_DELAY_S}s")
                self._close_connection()
                self._stop_event.wait(RECONNECT_DELAY_S)
                continue

            # Stay connected until the socket drops or we are asked to stop.
            while not self._stop_event.is_set() and self._connected.is_set():
                self._stop_event.wait(1.0)

            if not self._stop_event.is_set():
                self._set_status(SourceStatus.RECONNECTING, "stream closed")
                print("[live:signalr] stream closed, reconnecting...")
                self._close_connection()
                self._stop_event.wait(RECONNECT_DELAY_S)

    def _shutdown(self) -> None:
        self._close_connection()
        with self._record_lock:
            if self._record_file is not None:
                try:
                    self._record_file.close()
                finally:
                    self._record_file = None
