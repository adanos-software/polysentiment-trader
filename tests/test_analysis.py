import csv

from polysentiment_trader.analysis import (
    load_markets,
    read_log_tail,
    render_analysis,
    sanitize_line,
    selected_quote,
)


def test_selected_quote_falls_back_to_side_price():
    assert selected_quote({"side": "YES", "yes_price": "0.42", "no_price": "0.58"}) == 0.42
    assert selected_quote({"side": "NO", "yes_price": "0.42", "no_price": "0.58"}) == 0.58
    assert selected_quote({"quote": "0.31", "side": "YES", "yes_price": "0.42"}) == 0.31


def test_render_analysis_shows_filter_pressure_and_near_misses():
    actions = {
        "strategy": {
            "min_liquidity": 10000,
            "min_market_trade_count": 10,
            "min_stock_trade_count": 20,
            "min_buzz_score": 35,
            "min_abs_sentiment": 0.12,
            "min_edge": 0.05,
            "min_confidence": 0.45,
            "min_evidence_quality_score": 0.55,
            "min_price": 0.25,
            "max_price": 0.60,
        },
        "portfolio": {
            "cash": 981.13,
            "equity": 981.13,
            "open_positions": 0,
            "closed_positions": 1,
            "realized_pnl": -18.87,
            "updated_at": "2026-05-08T19:50:03",
        },
        "closed_positions": [
            {
                "ticker": "OPEN",
                "side": "NO",
                "entry_price": 0.53,
                "current_price": 0.13,
                "realized_pnl": -18.87,
                "exit_reason": "stop_loss",
                "confidence": 0.452,
                "edge": 0.0557,
                "evidence_quality_score": 0.6,
            }
        ],
    }
    rows = [
        {
            "ticker": "TSLA",
            "action": "skipped",
            "reason": "weak_sentiment",
            "detail": "sentiment=0.02, buzz=80, trades=24, trend=rising",
            "side": "YES",
            "yes_price": "0.42",
            "no_price": "0.58",
            "edge": "0.052",
            "confidence": "0.47",
            "evidence_quality_score": "0.61",
            "liquidity": "15000",
            "market_trade_count": "12",
            "buzz_score": "80",
            "sentiment_score": "0.02",
            "trend": "rising",
            "question": "Will Tesla close above $300?",
        },
        {
            "ticker": "GOOGL",
            "action": "skipped",
            "reason": "low_market_flow",
            "detail": "sentiment=0.21, buzz=55, trades=22, trend=rising",
            "side": "YES",
            "yes_price": "0.51",
            "edge": "0.06",
            "confidence": "0.50",
            "evidence_quality_score": "0.64",
            "liquidity": "30000",
            "market_trade_count": "8",
            "buzz_score": "55",
            "sentiment_score": "0.21",
            "trend": "rising",
            "question": "Will Google close above $200?",
        },
        {
            "ticker": "MSFT",
            "action": "skipped",
            "reason": "market_closed",
            "detail": "inactive",
            "liquidity": "0",
            "market_trade_count": "0",
        },
    ]

    report = render_analysis(actions, rows, {}, ["cycle complete; skipped=2"], near_miss_limit=2)

    assert "PolySentimentTrader Performance Replay" in report
    assert "Cash: $981.13" in report
    assert "Realized PnL: $-18.87" in report
    assert "weak_sentiment=1" in report
    assert "Threshold Pressure" in report
    assert "Strategy-threshold rows: 2/3" in report
    assert "TSLA YES reason=weak_sentiment" in report
    assert "Recent stop-losses" in report


def test_load_markets_uses_actions_payload_when_csv_missing(tmp_path):
    actions = {"considered_markets": [{"ticker": "AAPL", "action": "skipped"}]}

    assert load_markets(tmp_path / "missing.csv", actions) == [{"ticker": "AAPL", "action": "skipped"}]


def test_load_markets_reads_csv(tmp_path):
    path = tmp_path / "markets.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "action"])
        writer.writeheader()
        writer.writerow({"ticker": "AAPL", "action": "opened"})

    assert load_markets(path, {}) == [{"ticker": "AAPL", "action": "opened"}]


def test_sanitize_line_redacts_common_secret_shapes():
    line = "Authorization: Bearer abc.def token=secret api_key=hidden"

    sanitized = sanitize_line(line)

    assert "abc.def" not in sanitized
    assert "secret" not in sanitized
    assert "hidden" not in sanitized
    assert "[REDACTED]" in sanitized


def test_read_log_tail_reads_bounded_tail_and_sanitizes(tmp_path):
    path = tmp_path / "bot.log"
    path.write_text(
        "\n".join(f"line {index} api_key=hidden" for index in range(20)),
        encoding="utf-8",
    )

    tail = read_log_tail(path, max_lines=3, max_bytes=80)

    assert len(tail) == 3
    assert tail[-1].startswith("line 19")
    assert "hidden" not in "\n".join(tail)
