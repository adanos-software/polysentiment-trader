from urllib.request import Request

import pytest

from polysentiment_trader.client import AdanosApiError, AdanosClient


def test_get_json_wraps_timeout_error(monkeypatch):
    client = AdanosClient(base_url="https://api.adanos.org", api_key="test-key", timeout_seconds=3.0)

    def raise_timeout(_request: Request, timeout: float):
        assert timeout == 3.0
        raise TimeoutError("timed out")

    monkeypatch.setattr("polysentiment_trader.client.urlopen", raise_timeout)

    with pytest.raises(AdanosApiError, match="Timed out reading"):
        client.get_polymarket_trending(days=1, limit=25)
