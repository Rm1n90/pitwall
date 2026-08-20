"""Driver portraits.

The driver list carries a headshot address for every entrant. They are fetched
once and kept on disk, so a replay shows a face beside the telemetry rather
than a three letter code.
"""

import os
from typing import Dict, Optional
from urllib.request import Request, urlopen

CACHE_SUBDIR = "headshots"
REQUEST_TIMEOUT = 20
USER_AGENT = "pitwall"

# Portraits are served through an image pipeline whose address contains a
# "fallback image" directive for every driver, real portrait or not, so the
# address says nothing about whether a portrait exists. Only the fetch does.


def _cache_path(cache_dir: str, code: str) -> str:
    safe = "".join(c for c in str(code) if c.isalnum()) or "unknown"
    return os.path.join(cache_dir, CACHE_SUBDIR, f"{safe}.png")


def fetch_headshot(code: str, url: str,
                   cache_dir: str = "computed_data") -> Optional[str]:
    """Return a local path to a driver's portrait, downloading it if needed.

    Returns ``None`` when there is no real portrait or it cannot be fetched,
    so callers can simply fall back to text.
    """
    if not url:
        return None

    path = _cache_path(cache_dir, code)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = response.read()
        if not data:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path
    except Exception as e:
        print(f"Portrait for {code} unavailable: {e}")
        return None


def fetch_for_session(session, cache_dir: str = "computed_data"
                      ) -> Dict[str, str]:
    """Return ``{code: local_path}`` for every driver with a portrait."""
    portraits: Dict[str, str] = {}
    results = getattr(session, "results", None)
    if results is None or results.empty:
        return portraits

    for _, row in results.iterrows():
        code = str(row.get("Abbreviation") or "")
        url = str(row.get("HeadshotUrl") or "")
        if not code:
            continue
        path = fetch_headshot(code, url, cache_dir)
        if path:
            portraits[code] = path
    return portraits


def paths_from_driver_list(drivers: Dict[str, dict],
                           code_for_number, cache_dir: str = "computed_data"
                           ) -> Dict[str, str]:
    """Return portraits for a live session's driver list."""
    portraits: Dict[str, str] = {}
    for number, info in (drivers or {}).items():
        if not isinstance(info, dict):
            continue
        code = str(code_for_number(str(number)))
        path = fetch_headshot(code, str(info.get("HeadshotUrl") or ""),
                              cache_dir)
        if path:
            portraits[code] = path
    return portraits
