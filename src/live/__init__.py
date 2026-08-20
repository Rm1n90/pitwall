"""Live (real-time) F1 session support.

This package turns the F1 live timing feeds into the exact same frame
structure that :func:`src.f1_data.get_race_telemetry` produces for replays,
so the existing replay window, leaderboard, telemetry stream and insight
windows all work unchanged while a session is running.

See ``docs/LiveMode.md`` for the architecture and data source details.
"""

__all__ = ["LiveConfig", "LiveRaceEngine", "LiveFrameBuffer", "LiveSessionState"]

_LAZY_EXPORTS = {
    "LiveConfig": "src.live.config",
    "LiveRaceEngine": "src.live.engine",
    "LiveFrameBuffer": "src.live.buffer",
    "LiveSessionState": "src.live.state",
}


def __getattr__(name):
    # Imported lazily so that lightweight helpers (schedule lookups, decoding)
    # can be used without pulling in numpy/scipy and the whole engine.
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)
