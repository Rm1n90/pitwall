"""Load a complete MotoGP session, ready for the replay window.

This is the orchestration layer that ties the data client, the Analysis PDF
parser, the circuit geometry and the frame builder into one call. It mirrors
what :func:`src.f1_data.get_race_telemetry` does for F1: given a year, event and
class, it returns a payload the replay window can render directly.

Downloaded Analysis PDFs and circuit SVGs are cached on disk, the same way
FastF1 caches F1 data, so a session is fetched once. The sheets are copyright
Dorna; they are cached locally and never redistributed.
"""

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from src.motogp import frame_builder, geometry, timing_pdf
from src.motogp.client import MotoGPClient


def _default_fetch_bytes(url: str) -> bytes:
    import requests

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def _cached_download(url: str, dest: str,
                     fetch_bytes: Callable[[str], bytes]) -> str:
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(fetch_bytes(url))
    return dest


@dataclass
class MotoGPReplay:
    """Everything the replay window needs to show a MotoGP session."""
    frames: list
    example_lap: object
    drivers: List[str]
    driver_colors: dict
    total_laps: Optional[int]
    circuit_rotation: float
    title: str
    session_type: str
    circuit: object
    pit_lane: list = None


def _find(items, predicate, what: str):
    for item in items:
        if predicate(item):
            return item
    raise LookupError(f"could not find {what}")


def load_race(year: int, event_short: str, category_name: str = "MotoGP",
              session_code: str = "RAC",
              client: Optional[MotoGPClient] = None,
              cache_dir: str = "computed_data/motogp",
              fetch_bytes: Callable[[str], bytes] = _default_fetch_bytes,
              fps: int = 25) -> MotoGPReplay:
    """Load one MotoGP race/sprint session into a renderable payload.

    Args:
        year: Season year, e.g. ``2025``.
        event_short: Event short name, e.g. ``"THA"``.
        category_name: ``"MotoGP"``, ``"Moto2"`` or ``"Moto3"``.
        session_code: Session code, e.g. ``"RAC"`` or ``"SPR"``.
        client: Data client; a default one is created if omitted.
        cache_dir: Where downloaded PDFs and SVGs are cached.
        fetch_bytes: Byte downloader, injectable for testing.
        fps: Output frame rate.
    """
    client = client or MotoGPClient()

    season = _find(client.seasons(), lambda s: s.year == year, f"season {year}")
    events = client.events(season.id, finished=True)
    event = _find(events, lambda e: e.short_name == event_short,
                  f"event {event_short} in {year}")
    categories = client.categories(event.id)
    category = _find(categories, lambda c: c.name == category_name,
                     f"category {category_name}")
    sessions = client.sessions(event.id, category.id)
    # The race code is "RAC" most years but "RAC2" in some (the broadcast and
    # results feeds have differed), so treat them as the same session.
    wanted = {"RAC", "RAC2"} if session_code in ("RAC", "RAC2") else {session_code}
    session = _find(sessions, lambda s: s.code in wanted,
                    f"session {session_code}")
    classification = client.classification(session.id)
    riders_by_number = _riders_by_number(client, year)

    # Circuit geometry from the broadcast schedule's outline SVG.
    circuit = circuit_geometry(client, year, event.circuit.name,
                               cache_dir, fetch_bytes)

    # Timing from the Analysis PDF.
    if not session.analysis_url:
        raise LookupError(f"no Analysis sheet for {event_short} {session_code}")
    pdf_dest = os.path.join(
        cache_dir, "analysis",
        f"{year}_{event_short}_{category_name}_{session_code}.pdf")
    _cached_download(session.analysis_url, pdf_dest, fetch_bytes)
    sheet = timing_pdf.parse_analysis(pdf_dest)

    built = frame_builder.build_race_frames(
        sheet, circuit, classification=classification,
        riders=riders_by_number, fps=fps,
        session_type="S" if session_code == "SPR" else "R")

    title = (f"{event.sponsored_name or event.name} — "
             f"{category_name} {'Sprint' if session_code == 'SPR' else 'Race'}")
    return MotoGPReplay(
        frames=built["frames"],
        example_lap=circuit.example_lap,
        drivers=list(built["driver_colors"].keys()),
        driver_colors=built["driver_colors"],
        total_laps=built["total_laps"],
        circuit_rotation=circuit.rotation,
        title=title,
        session_type=built["session_type"],
        circuit=circuit,
        pit_lane=circuit.pit_lane,
    )


def _riders_by_number(client: MotoGPClient, year: int) -> dict:
    """Map rider race number to rider metadata for colours and names."""
    by_number = {}
    for rider in client.riders(year):
        if rider.number is not None:
            by_number[rider.number] = rider
    return by_number


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (text or "circuit"))


def circuit_geometry(client, year, circuit_name,
                     cache_dir: str = "computed_data/motogp",
                     fetch_bytes=_default_fetch_bytes):
    """Fetch and build circuit geometry for a circuit by name.

    The outline SVG and official length come from the broadcast schedule, keyed
    on circuit name (the only identifier both the results and broadcast feeds,
    and the live feed, agree on).
    """
    schedule = client.schedule(year)
    entry = _find(schedule, lambda e: e.circuit_name == circuit_name,
                  f"circuit {circuit_name} in {year} schedule")
    length_m = entry.circuit_length_m or 4500.0
    svg_dest = os.path.join(cache_dir, "circuits", f"{_slug(circuit_name)}.svg")
    _cached_download(entry.circuit_svg_url, svg_dest, fetch_bytes)
    return geometry.circuit_from_svg(svg_dest, length_m)


def build_live_engine(client: Optional[MotoGPClient] = None,
                      cache_dir: str = "computed_data/motogp",
                      fetch_bytes=_default_fetch_bytes,
                      poll_interval_s: float = 5.0):
    """Build a live engine for whatever MotoGP session is running now.

    Returns ``(engine, circuit, live)``. Raises ``LookupError`` if the feed is
    not reporting a session or its circuit is not in the schedule.
    """
    from src.motogp.live import MotoGPLiveEngine

    client = client or MotoGPClient()
    live = client.live_timing()
    if not live.circuit_name:
        raise LookupError("the live timing feed is not reporting a session")
    season = next((s for s in client.seasons() if s.current), None)
    year = season.year if season else 2025
    circuit = circuit_geometry(client, year, live.circuit_name,
                               cache_dir, fetch_bytes)
    engine = MotoGPLiveEngine(client, circuit, poll_interval_s=poll_interval_s)
    return engine, circuit, live
