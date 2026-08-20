"""Common interface shared by every live data source."""

import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.live.decoding import LiveMessage

MessageHandler = Callable[[LiveMessage], None]


class SourceStatus:
    """Connection states a source can report."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    FAILED = "failed"


class LiveDataSource(ABC):
    """Base class for anything that can emit :class:`LiveMessage` objects.

    Subclasses run their own background thread and push decoded messages to
    the handler supplied to :meth:`start`. They must never raise out of that
    thread: transport problems are reported through :attr:`status` and
    :attr:`last_error` so that the session keeps running (possibly degraded)
    instead of taking the replay window down with it.
    """

    #: Human readable name used in log output and the on-screen live badge.
    name = "source"

    def __init__(self):
        self._handler: Optional[MessageHandler] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status = SourceStatus.IDLE
        self._status_lock = threading.Lock()
        self.last_error: Optional[str] = None
        #: Number of messages successfully emitted, useful for diagnostics.
        self.message_count = 0

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    def _set_status(self, status: str, error: Optional[str] = None) -> None:
        with self._status_lock:
            self._status = status
        if error:
            self.last_error = error

    def start(self, handler: MessageHandler) -> None:
        """Start streaming messages to ``handler`` on a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._handler = handler
        self._stop_event.clear()
        self._set_status(SourceStatus.CONNECTING)
        self._thread = threading.Thread(
            target=self._run_guarded, name=f"live-{self.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the source to stop and wait briefly for it to finish."""
        self._stop_event.set()
        try:
            self._shutdown()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            print(f"[live:{self.name}] error during shutdown: {exc}")
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._set_status(SourceStatus.STOPPED)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def emit(self, message: Optional[LiveMessage]) -> None:
        """Forward a decoded message to the handler."""
        if message is None or self._handler is None:
            return
        self.message_count += 1
        try:
            self._handler(message)
        except Exception as exc:  # pragma: no cover - handler must not kill us
            print(f"[live:{self.name}] message handler error: {exc}")

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._set_status(SourceStatus.FAILED, str(exc))
            print(f"[live:{self.name}] stopped with error: {exc}")

    @abstractmethod
    def _run(self) -> None:
        """Body of the background thread. Must respect ``self._stop_event``."""

    def _shutdown(self) -> None:
        """Optional hook for releasing transport resources."""
