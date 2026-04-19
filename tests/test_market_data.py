from datetime import datetime

from polysentiment_trader.market_data import MarketResolver, QuoteAdapter, extract_token_ids


def payload(**overrides):
    data = {
        "condition_id": "c1",
        "question": "Will Apple (AAPL) close above $240 this week?",
        "market_type": "close_above",
        "yes_price": 0.42,
        "no_price": 0.58,
        "liquidity": 20_000.0,
        "volume_24h": 5_000.0,
        "trade_count": 12,
        "sentiment_score": 0.4,
        "active": True,
        "end_date": "2026-04-20",
    }
    data.update(overrides)
    return data


def test_resolver_normalizes_market_and_token_ids_from_outcomes():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(outcomes='["Yes","No"]', clob_token_ids='["yes-token","no-token"]'),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert issue is None
    assert market is not None
    assert market.condition_id == "c1"
    assert market.yes_token_id == "yes-token"
    assert market.no_token_id == "no-token"


def test_resolver_rejects_expired_market():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(end_date="2026-04-18"),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert market is None
    assert issue is not None
    assert issue.reason == "market_closed"
    assert "end_date=2026-04-18" in issue.detail


def test_resolver_rejects_missing_condition_id():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(condition_id=""),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert market is None
    assert issue is not None
    assert issue.reason == "market_missing_condition_id"


def test_resolver_rejects_invalid_probability_price():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(yes_price=1.25),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )

    assert market is None
    assert issue is not None
    assert issue.reason == "price_out_of_range"


def test_quote_adapter_requires_token_id_when_requested():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )
    assert issue is None
    assert market is not None

    quote, quote_issue = QuoteAdapter().quote(market, "YES", require_token_id=True)

    assert quote is None
    assert quote_issue is not None
    assert quote_issue.reason == "missing_token_id"


def test_quote_adapter_returns_snapshot_quote_when_token_id_not_required():
    market, issue = MarketResolver().resolve(
        "AAPL",
        payload(),
        now=datetime(2026, 4, 19, 12, 0, 0),
    )
    assert issue is None
    assert market is not None

    quote, quote_issue = QuoteAdapter().quote(market, "YES")

    assert quote_issue is None
    assert quote is not None
    assert quote.reference_price == 0.42
    assert quote.source == "adanos_snapshot"


def test_extract_token_ids_from_token_objects():
    yes, no = extract_token_ids(
        {
            "tokens": [
                {"outcome": "No", "token_id": "no-token"},
                {"outcome": "Yes", "token_id": "yes-token"},
            ]
        }
    )

    assert yes == "yes-token"
    assert no == "no-token"
