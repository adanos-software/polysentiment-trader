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
