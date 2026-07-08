"""Minimal HTTP client for the SimBoard REST API.

Stdlib only — no new dependency. Reads JSON from
https://simboard-dev-api.e3sm.org/api/v1/ by default; override via the
SIMBOARD_API_BASE env var when the production deployment lands.

This is a *prototype* client. It does not handle pagination cursors,
retries, auth tokens, or anything else a production client would need.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE = "https://simboard-dev-api.e3sm.org/api/v1"


class SimBoardClient:
    """Thin wrapper around the SimBoard REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("SIMBOARD_API_BASE", DEFAULT_BASE)
        ).rstrip("/")
        self.token = token or os.environ.get("SIMBOARD_API_TOKEN")
        self.timeout_s = timeout_s
        self._ctx = ssl.create_default_context()

    # ---- low-level ----

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean, doseq=True)}"
        headers = {"User-Agent": "uxarray-mcp-simboard-bridge/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                req, context=self._ctx, timeout=self.timeout_s
            ) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read(500).decode(errors="ignore") if e.fp else ""
            raise RuntimeError(
                f"SimBoard GET {url} failed: HTTP {e.code} — {body[:200]}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"SimBoard GET {url} unreachable: {e.reason}") from e

    # ---- typed endpoints ----

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def list_cases(self) -> list[dict[str, Any]]:
        return self._get("/cases")

    def list_simulations(
        self,
        case_name: str | None = None,
        case_group: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/simulations",
            params={"case_name": case_name, "case_group": case_group},
        )

    def get_simulation(self, sim_id: str) -> dict[str, Any]:
        return self._get(f"/simulations/{sim_id}")
