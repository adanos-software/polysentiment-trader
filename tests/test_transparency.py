import csv
import json
from datetime import datetime

from polysentiment_trader.engine import PaperTrader, Portfolio, StrategyConfig
from polysentiment_trader.transparency import build_actions_payload, public_base_url, write_transparency_exports

from tests.factories import detail, market, stock


def test_actions_payload_includes_orders_skips_and_portfolio():
    config = StrategyConfig(min_edge=0.001)
    run = PaperTrader(config).run(
        [stock(), stock(ticker="MSFT", sentiment=0.01)],
        [detail()],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 20, 12, 0, 0),
    )

    payload = build_actions_payload(
        run,
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        base_url="https://api.adanos.org",
        mode="paper",
        config=config,
        scan_limit=25,
        days=1,
        dry_run=False,
    )

    assert payload["portfolio"]["cash"] == 975.0
    assert payload["actions"][0]["ticker"] == "AAPL"
    assert payload["actions"][0]["action"] == "open_position"
    assert payload["skipped_counts"]["weak_sentiment"] == 1
    assert payload["candidate_action_counts"]["opened"] == 1
    assert payload["candidate_reason_counts"]["weak_sentiment"] == 1
    assert payload["considered_markets_count"] >= 2
    assert "api_key" not in str(payload).lower()


def test_transparency_exports_write_json_and_csv(tmp_path):
    config = StrategyConfig(min_edge=0.001)
    run = PaperTrader(config).run(
        [stock()],
        [detail(markets=[market(), market(condition_id="c2", yes=0.99, no=0.01)])],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 20, 12, 0, 0),
    )
    actions_path = tmp_path / "latest-actions.json"
    markets_path = tmp_path / "considered.csv"

    write_transparency_exports(
        actions_path=actions_path,
        markets_path=markets_path,
        run=run,
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        base_url="https://api.adanos.org",
        mode="paper",
        config=config,
        scan_limit=25,
        days=1,
        dry_run=True,
    )

    payload = json.loads(actions_path.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["candidate_action_counts"]["opened"] == 1

    rows = list(csv.DictReader(markets_path.open(encoding="utf-8")))
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["condition_id"] == "c1"


def test_transparency_exports_can_be_disabled(tmp_path):
    config = StrategyConfig(min_edge=0.001)
    run = PaperTrader(config).run(
        [stock()],
        [detail()],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 20, 12, 0, 0),
    )

    write_transparency_exports(
        actions_path=None,
        markets_path=None,
        run=run,
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        base_url="https://api.adanos.org",
        mode="paper",
        config=config,
        scan_limit=25,
        days=1,
        dry_run=True,
    )

    assert list(tmp_path.iterdir()) == []


def test_public_base_url_removes_non_public_url_parts():
    assert public_base_url("https://user:pass@api.adanos.org/polymarket?api_key=secret#frag") == (
        "https://api.adanos.org/polymarket"
    )
