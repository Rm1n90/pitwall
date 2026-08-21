"""Qt-free helpers for wiring MotoGP into the session selection window.

These are kept out of the Qt module so the launch-command and row-shaping logic
can be unit tested without a display or PySide6.
"""

from typing import List

# Session buttons offered for a MotoGP event, as (label, category, code). The
# race code is "RAC"; sessions that did not run for a given event simply fail to
# load and are reported by the launched process.
MOTOGP_SESSION_BUTTONS = (
    ("MotoGP Race", "MotoGP", "RAC"),
    ("MotoGP Sprint", "MotoGP", "SPR"),
    ("Moto2 Race", "Moto2", "RAC"),
    ("Moto3 Race", "Moto3", "RAC"),
)


def motogp_event_rows(events) -> List[dict]:
    """Shape :class:`~src.motogp.models.Event` objects into schedule-tree rows.

    Test events (pre-season shakedowns) are dropped; only race weekends are
    offered. Each row mirrors the F1 row keys the tree already understands, plus
    the MotoGP identity fields the launcher needs.
    """
    rows = []
    for index, event in enumerate(events, 1):
        if getattr(event, "test", False):
            continue
        rows.append({
            "series": "motogp",
            "round_number": index,
            "event_name": event.sponsored_name or event.name or event.short_name,
            "country": event.country_iso or "",
            "date": "",
            "short_name": event.short_name,
            "circuit_name": event.circuit.name if event.circuit else None,
        })
    return rows


def build_motogp_command(python: str, main_path: str, year, event_short: str,
                         category: str, session_code: str,
                         verbose: bool = False) -> List[str]:
    """Build the ``main.py --motogp`` command line for a launch."""
    cmd = [python, main_path, "--motogp",
           "--year", str(year),
           "--event", str(event_short),
           "--class", str(category),
           "--session", str(session_code)]
    if verbose:
        cmd.append("--verbose")
    return cmd
