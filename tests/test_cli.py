import argparse

import pytest

from polysentiment_trader import cli
from polysentiment_trader.client import AdanosApiError

from tests.factories import detail, market, stock


class FakeClient:
    def __init__(self, **_kwargs):
        pass

    def get_polymarket_trending(self, days, limit):
        return [stock()]

    def get_polymarket_stock(self, ticker, days):
        return detail(ticker=ticker)


class FakePartialFailureClient(FakeClient):
    def get_polymarket_trending(self, days, limit):
        return [stock(ticker="AAPL"), stock(ticker="MSFT")]

    def get_polymarket_stock(self, ticker, days):
        if ticker == "AAPL":
            raise AdanosApiError("Timed out reading https://api.adanos.org/test after 20.0s")
        return detail(
            ticker=ticker,
            markets=[market(question=f"Will {ticker} close above $240 this week?")],
        )


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
        min_price=0.05,
        max_price=0.85,
        stop_loss_pct=-0.20,
        take_profit_pct=0.35,
        take_profit_cooldown_minutes=240,
        max_stop_losses_per_day=1,
        require_clob_token_ids=False,
        ledger=str(tmp_path / "paper-portfolio.json"),
        actions_out=str(tmp_path / "latest-actions.json"),
        markets_out=str(tmp_path / "considered.csv"),
        days=1,
        scan_limit=25,
        no_write=False,
    )


def test_build_parser_exposes_risk_controls():
    parser = cli.build_parser()

    args = parser.parse_args(["--api-key", "test-key"])

    assert args.min_edge == pytest.approx(0.04)
    assert args.min_abs_sentiment == pytest.approx(0.18)
    assert args.max_price == pytest.approx(0.65)
    assert args.take_profit_cooldown_minutes == 240
    assert args.max_stop_losses_per_day == 1


def test_build_parser_uses_current_working_directory_for_runtime_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)
    monkeypatch.delenv("POLYSENTIMENT_ACTIONS_OUT", raising=False)
    monkeypatch.delenv("POLYSENTIMENT_MARKETS_OUT", raising=False)
    (tmp_path / ".env").write_text("ADANOS_API_KEY=env-key\n", encoding="utf-8")

    parser = cli.build_parser()
    args = parser.parse_args([])

    assert args.api_key == "env-key"
    assert args.ledger == str(tmp_path / "data" / "paper-portfolio.json")
    assert args.actions_out == str(tmp_path / "data" / "latest-actions.json")
    assert args.markets_out == str(tmp_path / "data" / "considered-markets-latest.csv")


def test_run_once_saves_ledger_before_transparency_export_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "AdanosClient", FakeClient)

    def fail_export(**_kwargs):
        raise RuntimeError("export failed")

    monkeypatch.setattr(cli, "write_transparency_exports", fail_export)

    with pytest.raises(RuntimeError, match="export failed"):
        cli.run_once(args_for(tmp_path))

    assert (tmp_path / "paper-portfolio.json").exists()


def test_run_once_skips_stock_detail_api_failures(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "AdanosClient", FakePartialFailureClient)

    cli.run_once(args_for(tmp_path))

    captured = capsys.readouterr()
    assert "Skipped stock detail fetches" in captured.out
    assert "AAPL: Timed out reading" in captured.out
    assert (tmp_path / "paper-portfolio.json").exists()
    assert (tmp_path / "latest-actions.json").exists()


def test_loop_logs_failure_and_continues_to_next_cycle(tmp_path, capsys):
    args = args_for(tmp_path)
    args.loop = True
    args.cycles = 2
    args.interval_minutes = 0.1
    calls = []

    def run_cycle(_args):
        calls.append("cycle")
        if len(calls) == 1:
            raise AdanosApiError("HTTP 503 from https://api.adanos.org/test")

    sleeps = []

    cli.run_loop(args, run_cycle=run_cycle, sleep=lambda seconds: sleeps.append(seconds))

    captured = capsys.readouterr()
    assert calls == ["cycle", "cycle"]
    assert "Cycle 1 failed; skipping until next interval." in captured.out
    assert "AdanosApiError" in captured.err
    assert sleeps == [6.0]
