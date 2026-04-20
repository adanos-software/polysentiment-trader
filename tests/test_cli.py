import argparse

import pytest

from polysentiment_trader import cli

from tests.factories import detail, stock


class FakeClient:
    def __init__(self, **_kwargs):
        pass

    def get_polymarket_trending(self, days, limit):
        return [stock()]

    def get_polymarket_stock(self, ticker, days):
        return detail(ticker=ticker)


def args_for(tmp_path):
    return argparse.Namespace(
        base_url="https://api.adanos.org",
        api_key="test-key",
        timeout=1.0,
        bankroll=1000.0,
        max_positions=5,
        max_stake=25.0,
        min_edge=0.001,
        min_buzz_score=40.0,
        min_abs_sentiment=0.12,
        require_clob_token_ids=False,
        ledger=str(tmp_path / "paper-portfolio.json"),
        actions_out=str(tmp_path / "latest-actions.json"),
        markets_out=str(tmp_path / "considered.csv"),
        days=1,
        scan_limit=25,
        no_write=False,
    )


def test_run_once_saves_ledger_before_transparency_export_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "AdanosClient", FakeClient)

    def fail_export(**_kwargs):
        raise RuntimeError("export failed")

    monkeypatch.setattr(cli, "write_transparency_exports", fail_export)

    with pytest.raises(RuntimeError, match="export failed"):
        cli.run_once(args_for(tmp_path))

    assert (tmp_path / "paper-portfolio.json").exists()
