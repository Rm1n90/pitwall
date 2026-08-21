"""HTTP client for the MotoGP pulselive API.

Every method fetches one endpoint and hands the decoded JSON to a ``parse_*``
function in :mod:`src.motogp.models`. Fetching is isolated behind a ``getter``
callable so the client can be driven from recorded fixtures in tests without a
network round trip.

The API is read-only and unauthenticated. No key, cookie or token is sent.
"""

from typing import Callable, List, Optional
from urllib.parse import urlencode

from src.motogp import models

BASE_URL = "https://api.motogp.pulselive.com/motogp/v1"

# A polite timeout: the endpoints answer in well under a second normally.
DEFAULT_TIMEOUT_S = 20


def _requests_getter(url: str):
    import requests

    response = requests.get(url, timeout=DEFAULT_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


class MotoGPClient:
    """Read-only client for schedule, results and live timing.

    Args:
        getter: Callable taking a full URL and returning decoded JSON. Defaults
            to a plain ``requests.get``. Tests pass a fixture-backed getter.
        base_url: Override the API root, mainly for testing.
    """

    def __init__(self, getter: Optional[Callable[[str], object]] = None,
                 base_url: str = BASE_URL):
        self._get = getter or _requests_getter
        self._base = base_url.rstrip("/")

    def _url(self, path: str, **params) -> str:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{self._base}/{path.lstrip('/')}"
        return f"{url}?{urlencode(query)}" if query else url

    def seasons(self) -> List[models.Season]:
        return models.parse_seasons(self._get(self._url("results/seasons")))

    def events(self, season_id: str, finished: bool = True
               ) -> List[models.Event]:
        url = self._url("results/events", seasonUuid=season_id,
                        isFinished=str(finished).lower())
        return models.parse_events(self._get(url))

    def categories(self, event_id: str) -> List[models.Category]:
        url = self._url("results/categories", eventUuid=event_id)
        return models.parse_categories(self._get(url))

    def sessions(self, event_id: str, category_id: str
                 ) -> List[models.SessionRef]:
        url = self._url("results/sessions", eventUuid=event_id,
                        categoryUuid=category_id)
        return models.parse_sessions(self._get(url))

    def classification(self, session_id: str, test: bool = False
                       ) -> List[models.ClassificationRow]:
        url = self._url(f"results/session/{session_id}/classification",
                        test=str(test).lower())
        return models.parse_classification(self._get(url))

    def riders(self, year: int) -> List[models.Rider]:
        return models.parse_riders(
            self._get(self._url("riders", seasonYear=year)))

    def live_timing(self) -> models.LiveTiming:
        url = self._url("timing-gateway/livetiming-lite")
        return models.parse_livetiming(self._get(url))

    def schedule(self, year: int) -> List["models.ScheduleEntry"]:
        """Broadcast schedule: circuit outlines and per-session live status."""
        return models.parse_schedule(self._get(self._url("events", seasonYear=year)))
