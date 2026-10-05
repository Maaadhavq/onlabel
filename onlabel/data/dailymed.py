"""DailyMed web services (v2): find a label's set_id, list its versions, fetch its SPL XML.

A label is identified by its set_id, not by a brand name: Wegovy injection and Wegovy
tablets share one set_id, and repackagers publish their own copies under other set_ids.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"


@dataclass(frozen=True)
class SplHit:
    set_id: str
    title: str
    spl_version: int
    published_date: str


class DailyMed:
    def __init__(self, client: httpx.Client | None = None, pause_s: float = 0.25) -> None:
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)
        self.pause_s = pause_s  # be polite: NLM asks clients not to hammer the service

    def _get(self, url: str, **params) -> httpx.Response:
        for attempt in range(4):
            try:
                r = self.client.get(url, params=params or None)
                r.raise_for_status()
                time.sleep(self.pause_s)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == 3 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404):
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def search(self, drug_name: str) -> list[SplHit]:
        rows = self._get(f"{BASE}/spls.json", drug_name=drug_name).json().get("data", [])
        return [
            SplHit(r["setid"], r["title"], int(r["spl_version"]), r["published_date"]) for r in rows
        ]

    def history(self, set_id: str) -> list[tuple[int, str]]:
        """(spl_version, published_date), newest first."""
        data = self._get(f"{BASE}/spls/{set_id}/history.json").json()["data"]
        return [(int(r["spl_version"]), r["published_date"]) for r in data["history"]]

    def spl_xml(self, set_id: str) -> bytes:
        """The current version's SPL document."""
        return self._get(f"{BASE}/spls/{set_id}.xml").content
