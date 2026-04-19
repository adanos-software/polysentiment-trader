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


def stock(ticker="AAPL", sentiment=0.6, buzz=80.0, trend="rising"):
    return {
        "ticker": ticker,
        "company_name": "Apple Inc.",
        "buzz_score": buzz,
        "trend": trend,
        "trade_count": 80,
        "sentiment_score": sentiment,
        "total_liquidity": 150_000.0,
    }


def market(
    question="Will Apple (AAPL) close above $240 this week?",
    market_type="close_above",
    yes=0.45,
    no=0.55,
    sentiment=0.4,
    **overrides,
):
    data = {
        "condition_id": "c1",
        "question": question,
        "market_type": market_type,
        "trade_count": 12,
        "sentiment_score": sentiment,
        "yes_price": yes,
        "no_price": no,
        "liquidity": 20_000.0,
        "volume_24h": 5_000.0,
        "active": True,
    }
    data.update(overrides)
    return data


def detail(ticker="AAPL", markets=None):
    return {"ticker": ticker, "found": True, "top_mentions": markets if markets is not None else [market()]}


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
