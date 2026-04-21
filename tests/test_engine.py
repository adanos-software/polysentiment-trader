from datetime import datetime

import pytest

from polysentiment_trader.engine import (
    PaperTrader,
    Portfolio,
    Position,
    StrategyConfig,
    derive_yes_direction,
    format_report,
    load_portfolio,
    save_portfolio,
)
from tests.factories import detail, market, stock


def test_derive_yes_direction_handles_common_market_shapes():
    assert derive_yes_direction("up_down", "NVIDIA (NVDA) Up or Down on April 20?", "NVDA") == 1
    assert derive_yes_direction("other", "Will Apple (AAPL) dip to $120 in April?", "AAPL") == -1
    assert derive_yes_direction("other", "Will NVIDIA (NVDA) outperform Bitcoin?", "NVDA") == 1
    assert derive_yes_direction("other", "Will Bitcoin outperform NVIDIA (NVDA)?", "NVDA") == -1


def test_trader_buys_yes_for_bullish_signal():
    trader = PaperTrader(StrategyConfig(min_edge=0.001, max_stake=25.0))
    portfolio = Portfolio.new(1000.0)

    run = trader.run([stock()], [detail()], portfolio, now=datetime(2026, 4, 19, 12, 0, 0))

    assert len(run.orders) == 1
    assert run.orders[0].side == "YES"
    assert run.orders[0].stake == pytest.approx(25.0)
    assert run.orders[0].evidence_quality_score >= trader.config.min_evidence_quality_score
    assert run.orders[0].counter_case
    assert portfolio.cash == pytest.approx(975.0)


def test_trader_buys_yes_when_yes_is_bearish_and_signal_is_bearish():
    trader = PaperTrader(StrategyConfig(min_edge=0.001, max_stake=25.0))
    bearish_market = market(
        question="Will Apple (AAPL) dip to $120 in April?",
        market_type="other",
        yes=0.40,
        no=0.60,
        sentiment=-0.5,
    )

    run = trader.run(
        [stock(sentiment=-0.55)],
        [detail(markets=[bearish_market])],
        Portfolio.new(1000.0),
    )

    assert len(run.orders) == 1
    assert run.orders[0].side == "YES"
    assert run.orders[0].price == pytest.approx(0.40)


def test_mark_to_market_closes_take_profit():
    trader = PaperTrader(StrategyConfig(take_profit_pct=0.35))
    portfolio = Portfolio(
        initial_bankroll=100.0,
        cash=80.0,
        positions=[
            Position(
                ticker="AAPL",
                condition_id="c1",
                question="Will Apple (AAPL) close above $240 this week?",
                side="YES",
                shares=50.0,
                entry_price=0.40,
                current_price=0.40,
                stake=20.0,
                opened_at="2026-04-19T10:00:00",
                thesis="test",
                confidence=0.8,
                edge=0.1,
            )
        ],
    )

    exits = trader.mark_to_market(
        portfolio,
        trader._details_by_ticker([detail(markets=[market(yes=0.56, no=0.44)])]),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert len(exits) == 1
    assert exits[0].reason == "take_profit"
    assert exits[0].pnl == pytest.approx(8.0)
    assert portfolio.cash == pytest.approx(108.0)


def test_portfolio_round_trip(tmp_path):
    path = tmp_path / "portfolio.json"
    portfolio = Portfolio.new(500.0)
    save_portfolio(path, portfolio)

    loaded = load_portfolio(path, initial_bankroll=500.0)

    assert loaded.initial_bankroll == pytest.approx(500.0)
    assert loaded.cash == pytest.approx(500.0)


def test_report_includes_entries_and_skips():
    trader = PaperTrader(StrategyConfig(min_edge=0.001))
    run = trader.run(
        [stock(), stock(ticker="MSFT", sentiment=0.01)],
        [detail()],
        Portfolio.new(1000.0),
    )

    report = format_report(run)

    assert "POLYSENTIMENT TRADER" in report
    assert "AAPL   BUY YES" in report
    assert "weak_sentiment=1" in report
    assert "\nDecision" in report
    assert any(trace.action == "opened" for trace in run.considered_markets)
    assert any(trace.reason == "weak_sentiment" for trace in run.considered_markets)


def test_trader_traces_markets_skipped_by_position_capacity():
    trader = PaperTrader(StrategyConfig(max_positions=1, min_edge=0.001))
    portfolio = Portfolio(
        initial_bankroll=100.0,
        cash=75.0,
        positions=[
            Position(
                ticker="AAPL",
                condition_id="open-aapl",
                question="Will Apple (AAPL) close above $240 this week?",
                side="YES",
                shares=55.0,
                entry_price=0.45,
                current_price=0.45,
                stake=25.0,
                opened_at="2026-04-19T10:00:00",
                thesis="existing position",
                confidence=0.8,
                edge=0.1,
            )
        ],
    )

    run = trader.run(
        [stock(ticker="MSFT")],
        [detail(ticker="MSFT", markets=[market(condition_id="msft-market")])],
        portfolio,
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert len(run.orders) == 0
    assert run.rejection_counts()["max_positions_reached"] == 1
    assert run.considered_markets[0].condition_id == "msft-market"
    assert run.considered_markets[0].reason == "max_positions_reached"


def test_trader_skips_expired_markets_before_price_filter():
    trader = PaperTrader(StrategyConfig(min_edge=0.001))
    expired_market = market(yes=0.0005, no=0.9995, end_date="2026-04-18")

    run = trader.run(
        [stock()],
        [detail(markets=[expired_market])],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert len(run.orders) == 0
    assert run.rejection_counts()["market_closed"] == 1
    assert "price_out_of_range" not in run.rejection_counts()
    assert run.considered_markets[0].reason == "market_closed"
    assert run.considered_markets[0].yes_price == pytest.approx(0.0005)


def test_trader_can_require_clob_token_ids():
    trader = PaperTrader(StrategyConfig(min_edge=0.001, require_clob_token_ids=True))

    run = trader.run(
        [stock()],
        [detail()],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert len(run.orders) == 0
    assert run.rejection_counts()["missing_token_id"] == 1


def test_trader_rejects_low_evidence_quality_market():
    trader = PaperTrader(StrategyConfig(min_edge=0.001, min_evidence_quality_score=0.45))

    run = trader.run(
        [stock(sentiment=0.13, buzz=45.0)],
        [
            detail(
                markets=[
                    market(
                        yes=0.40,
                        no=0.60,
                        sentiment=0.01,
                        liquidity=1100.0,
                        trade_count=1,
                        volume_24h=50.0,
                    )
                ]
            )
        ],
        Portfolio.new(1000.0),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert len(run.orders) == 0
    assert run.rejection_counts()["low_evidence_quality"] == 1
    assert run.considered_markets[0].evidence_quality_score is not None
    assert run.considered_markets[0].reason == "low_evidence_quality"
