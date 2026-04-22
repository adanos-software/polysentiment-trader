"""HTTP client for the Adanos Polymarket sentiment API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AdanosApiError(RuntimeError):
    """Raised when the Adanos API cannot return usable sentiment data."""


@dataclass(frozen=True)
class AdanosClient:
    """Small stdlib-only client for protected Polymarket endpoints."""

    base_url: str = "http://localhost:8000"
    api_key: Optional[str] = None
    timeout_seconds: float = 20.0

    def get_polymarket_trending(self, days: int, limit: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            "/polymarket/stocks/v1/trending",
            {"days": days, "limit": limit},
        )
        if not isinstance(payload, list):
            raise AdanosApiError("Unexpected /trending response shape")
        return [item for item in payload if isinstance(item, dict)]

    def get_polymarket_stock(self, ticker: str, days: int) -> Optional[dict[str, Any]]:
        try:
            payload = self._get_json(
                f"/polymarket/stocks/v1/stock/{ticker}",
                {"days": days},
            )
        except AdanosApiError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        if not isinstance(payload, dict):
            raise AdanosApiError(f"Unexpected /stock/{ticker} response shape")
        return payload if payload.get("found") else None

    def _get_json(self, path: str, query: dict[str, Any]) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AdanosApiError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except TimeoutError as exc:
            raise AdanosApiError(
                f"Timed out reading {url} after {self.timeout_seconds:.1f}s",
            ) from exc
        except URLError as exc:
            raise AdanosApiError(f"Could not reach {url}: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdanosApiError(f"Invalid JSON from {url}") from exc
