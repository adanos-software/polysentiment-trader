"""Read-only performance analysis for the latest paper-trading run."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ACTIONS_PATH = Path("data/latest-actions.json")
DEFAULT_MARKETS_PATH = Path("data/considered-markets-latest.csv")
DEFAULT_PORTFOLIO_PATH = Path("data/paper-portfolio.json")
DEFAULT_LOGPATH_FILE = Path("data/polysentiment-trader.logpath")

SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(api[_-]?key|authorization|password|secret|token)(\s*[:=]\s*)\S+"),
    re.compile(r"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&\s]+"),
)
STOCK_TRADES_RE = re.compile(r"\btrades=(\d+)\b")
DATA_QUALITY_REASONS = {
    "market_closed",
    "market_missing_condition_id",
    "market_missing_question",
    "invalid_market_payload",
    "missing_price",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def load_markets(path: Path, actions_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    if not actions_payload:
        return []
    rows = actions_payload.get("considered_markets")
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def load_log_path(logpath_file: Path) -> Path | None:
    if not logpath_file.exists():
        return None
    value = logpath_file.read_text(encoding="utf-8").strip()
    return Path(value).expanduser() if value else None


def read_log_tail(log_path: Path | None, max_lines: int = 120, max_bytes: int = 128_000) -> list[str]:
    if log_path is None or not log_path.exists():
        return []
    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        offset = max(0, size - max_bytes)
        handle.seek(offset)
        text = handle.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    if offset and lines:
        lines = lines[1:]
    return [sanitize_line(line) for line in lines[-max_lines:]]


def sanitize_line(line: str) -> str:
    sanitized = line
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(bearer)"):
            sanitized = pattern.sub(r"\1 [REDACTED]", sanitized)
        else:
            sanitized = pattern.sub(_redact_secret_match, sanitized)
    return sanitized


def _redact_secret_match(match: re.Match[str]) -> str:
    prefix = match.group(1) or ""
    separator = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
    return f"{prefix}{separator}[REDACTED]"


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fmt_money(value: Any) -> str:
    number = as_float(value)
    return "n/a" if number is None else f"${number:,.2f}"


def fmt_number(value: Any, digits: int = 3) -> str:
    number = as_float(value)
    return "n/a" if number is None else f"{number:.{digits}f}"


def selected_quote(row: dict[str, Any]) -> float | None:
    quote = as_float(row.get("quote"))
    if quote is not None:
        return quote
    side = str(row.get("side") or "").upper()
    if side == "YES":
        return as_float(row.get("yes_price"))
    if side == "NO":
        return as_float(row.get("no_price"))
    return None


def stock_trade_count(row: dict[str, Any]) -> int | None:
    detail = str(row.get("detail") or "")
    match = STOCK_TRADES_RE.search(detail)
    return int(match.group(1)) if match else None


def portfolio_summary(portfolio_payload: dict[str, Any], actions_payload: dict[str, Any]) -> dict[str, Any]:
    if portfolio_payload:
        open_positions = [
            item for item in portfolio_payload.get("positions", []) if isinstance(item, dict)
        ]
        closed_positions = [
            item for item in portfolio_payload.get("closed_positions", []) if isinstance(item, dict)
        ]
        cash = as_float(portfolio_payload.get("cash")) or 0.0
        market_value = sum(
            (as_float(item.get("shares")) or 0.0)
            * (as_float(item.get("current_price")) or 0.0)
            for item in open_positions
        )
        return {
            "cash": cash,
            "equity": cash + market_value,
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "realized_pnl": sum(as_float(item.get("realized_pnl")) or 0.0 for item in closed_positions),
            "updated_at": portfolio_payload.get("updated_at"),
            "closed_items": closed_positions,
        }

    summary = actions_payload.get("portfolio") if isinstance(actions_payload.get("portfolio"), dict) else {}
    return {
        "cash": summary.get("cash"),
        "equity": summary.get("equity"),
        "open_positions": summary.get("open_positions"),
        "closed_positions": summary.get("closed_positions"),
        "realized_pnl": summary.get("realized_pnl"),
        "updated_at": summary.get("updated_at"),
        "closed_items": actions_payload.get("closed_positions") or [],
    }


def count_values(rows: Iterable[dict[str, Any]], key: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = str(row.get(key) or "").strip() or "unknown"
        counts[value] += 1
    return counts


def pressure_line(label: str, failed: int, total: int, threshold: Any, near: int = 0) -> str:
    pct = (failed / total * 100.0) if total else 0.0
    near_text = f", near miss {near}" if near else ""
    return f"- {label}: {failed}/{total} ({pct:.1f}%) against {threshold}{near_text}"


def threshold_pressure(rows: list[dict[str, Any]], strategy: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not rows:
        return ["- No candidate rows available."]
    strategy_rows = [
        row for row in rows if str(row.get("reason") or "") not in DATA_QUALITY_REASONS
    ]
    lines.append(
        f"- Strategy-threshold rows: {len(strategy_rows)}/{len(rows)} after data-quality rejects"
    )
    if not strategy_rows:
        return lines

    def numeric_values(field: str) -> list[float]:
        values = [as_float(row.get(field)) for row in strategy_rows]
        return [value for value in values if value is not None]

    def numeric_failures(field: str, threshold_key: str, label: str) -> None:
        threshold = as_float(strategy.get(threshold_key))
        if threshold is None:
            return
        values = numeric_values(field)
        if not values:
            return
        failed = sum(1 for value in values if value < threshold)
        near = sum(1 for value in values if threshold > value >= threshold * 0.8)
        lines.append(pressure_line(label, failed, len(values), f">= {threshold:g}", near))

    numeric_failures("liquidity", "min_liquidity", "Liquidity floor")
    numeric_failures("market_trade_count", "min_market_trade_count", "Market flow floor")
    numeric_failures("buzz_score", "min_buzz_score", "Buzz floor")
    numeric_failures("confidence", "min_confidence", "Confidence floor")
    numeric_failures("evidence_quality_score", "min_evidence_quality_score", "Evidence floor")
    numeric_failures("edge", "min_edge", "Edge floor")

    stock_threshold = as_float(strategy.get("min_stock_trade_count"))
    if stock_threshold is not None:
        stock_values = [stock_trade_count(row) for row in strategy_rows]
        stock_values = [value for value in stock_values if value is not None]
        failed = sum(1 for value in stock_values if value < stock_threshold)
        near = sum(1 for value in stock_values if stock_threshold > value >= stock_threshold * 0.8)
        lines.append(pressure_line("Stock flow floor", failed, len(stock_values), f">= {stock_threshold:g}", near))

    sentiment_threshold = as_float(strategy.get("min_abs_sentiment"))
    sentiment_values = [as_float(row.get("sentiment_score")) for row in strategy_rows]
    sentiment_values = [value for value in sentiment_values if value is not None]
    if sentiment_threshold is not None and sentiment_values:
        failed = sum(1 for value in sentiment_values if abs(value) < sentiment_threshold)
        near = sum(1 for value in sentiment_values if sentiment_threshold > abs(value) >= sentiment_threshold * 0.8)
        lines.append(pressure_line("Absolute sentiment floor", failed, len(sentiment_values), f">= {sentiment_threshold:g}", near))

    min_price = as_float(strategy.get("min_price"))
    max_price = as_float(strategy.get("max_price"))
    quotes = [selected_quote(row) for row in strategy_rows]
    quotes = [quote for quote in quotes if quote is not None]
    if min_price is not None and max_price is not None and quotes:
        below = sum(1 for quote in quotes if quote < min_price)
        above = sum(1 for quote in quotes if quote > max_price)
        lines.append(
            f"- Price band: {below} below {min_price:g}, {above} above {max_price:g}, {len(quotes)} with selected quote"
        )

    falling = sum(1 for row in strategy_rows if str(row.get("trend") or "").lower() == "falling")
    if falling:
        lines.append(f"- Falling trend guard: {falling}/{len(strategy_rows)} rows marked falling")

    return lines or ["- No configured threshold pressure detected in available fields."]


def near_miss_score(row: dict[str, Any]) -> float:
    evidence = as_float(row.get("evidence_quality_score")) or 0.0
    confidence = as_float(row.get("confidence")) or 0.0
    edge = as_float(row.get("edge")) or 0.0
    liquidity = as_float(row.get("liquidity")) or 0.0
    market_trades = as_float(row.get("market_trade_count")) or 0.0
    quote = selected_quote(row) or 0.0
    score = evidence * 4.0 + confidence * 2.0 + edge * 8.0
    score += min(liquidity / 50_000.0, 1.0)
    score += min(market_trades / 25.0, 1.0)
    if 0.20 <= quote <= 0.70:
        score += 0.5
    if str(row.get("reason") or "") in {"market_closed", "unknown_market_direction"}:
        score -= 4.0
    return score


def near_misses(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if str(row.get("action") or "") == "skipped"
        and str(row.get("side") or "").upper() in {"YES", "NO"}
        and str(row.get("reason") or "") not in {"market_closed"}
    ]
    return sorted(candidates, key=near_miss_score, reverse=True)[:limit]


def summarize_closed_positions(closed_positions: list[dict[str, Any]], strategy: dict[str, Any]) -> list[str]:
    if not closed_positions:
        return ["- No closed positions yet."]

    by_reason = Counter(str(item.get("exit_reason") or "unknown") for item in closed_positions)
    lines = [
        "- Exit reasons: "
        + ", ".join(f"{reason}={count}" for reason, count in by_reason.most_common())
    ]
    pnl = sum(as_float(item.get("realized_pnl")) or 0.0 for item in closed_positions)
    lines.append(f"- Closed realized PnL: {fmt_money(pnl)}")

    latest = closed_positions[-1]
    confidence = as_float(latest.get("confidence"))
    edge = as_float(latest.get("edge"))
    evidence = as_float(latest.get("evidence_quality_score"))
    flags: list[str] = []
    min_confidence = as_float(strategy.get("min_confidence"))
    min_edge = as_float(strategy.get("min_edge"))
    min_evidence = as_float(strategy.get("min_evidence_quality_score"))
    if min_confidence is not None and confidence is not None and confidence <= min_confidence + 0.05:
        flags.append("confidence near threshold")
    if min_edge is not None and edge is not None and edge <= min_edge + 0.02:
        flags.append("edge near threshold")
    if min_evidence is not None and evidence is not None and evidence <= min_evidence + 0.08:
        flags.append("evidence near threshold")
    suffix = f" ({', '.join(flags)})" if flags else ""
    lines.append(
        "- Latest closed: "
        f"{latest.get('ticker', 'n/a')} {latest.get('side', 'n/a')} "
        f"entry {fmt_number(latest.get('entry_price'))}, exit {fmt_number(latest.get('current_price'))}, "
        f"PnL {fmt_money(latest.get('realized_pnl'))}, reason {latest.get('exit_reason', 'unknown')}{suffix}"
    )
    return lines


def summarize_log_tail(lines: list[str]) -> list[str]:
    if not lines:
        return ["- No log tail available."]
    keywords = ("cycle", "summary", "opened", "closed", "skip", "error", "stop", "pnl")
    relevant = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    selected = (relevant or lines)[-8:]
    errors = any("error" in line.lower() or "traceback" in line.lower() for line in lines)
    stops = any("stop" in line.lower() for line in lines)
    return [f"- Errors visible: {'yes' if errors else 'no'}; stops visible: {'yes' if stops else 'no'}"] + [
        f"- {line}" for line in selected
    ]


def recommendations(
    rows: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
    reason_counts: Counter[str],
    action_counts: Counter[str],
) -> list[str]:
    recs: list[str] = []
    total = sum(action_counts.values())
    skipped = action_counts.get("skipped", 0)
    stop_losses = [item for item in closed_positions if item.get("exit_reason") == "stop_loss"]

    if total and skipped == total:
        recs.append("- No entries in the latest trace: optimize the funnel/ranking before relaxing risk globally.")
    if reason_counts.get("weak_sentiment", 0) > max(3, total * 0.25):
        recs.append("- Weak sentiment dominates: improve signal quality or add watchlist confirmation; do not lower sentiment blindly.")
    if reason_counts.get("low_stock_flow", 0) + reason_counts.get("low_market_flow", 0) > max(3, total * 0.20):
        recs.append("- Flow filters are binding: split floors by market type instead of using one global liquidity/flow rule.")
    if reason_counts.get("price_out_of_range", 0) > max(2, total * 0.05):
        recs.append("- Price band is actively shaping risk; review separately for cheap tail contracts and expensive near-certain contracts.")
    if reason_counts.get("market_closed", 0) > max(3, total * 0.05):
        recs.append("- Closed/inactive markets are noise: pre-filter them earlier to save scan budget and make reports cleaner.")
    if stop_losses:
        recs.append("- Recent stop-losses argue for a confirmation delay or higher threshold on edge/confidence before new entries.")
    if near_misses(rows, 1):
        recs.append("- Use the listed near misses as a replay set: test threshold changes against these rows first, then change config.")
    return recs or ["- Current data is thin; keep thresholds unchanged until more closed trades or higher-quality near misses exist."]


def render_analysis(
    actions_payload: dict[str, Any],
    market_rows: list[dict[str, Any]],
    portfolio_payload: dict[str, Any],
    log_lines: list[str],
    *,
    near_miss_limit: int = 10,
) -> str:
    strategy = actions_payload.get("strategy") if isinstance(actions_payload.get("strategy"), dict) else {}
    portfolio = portfolio_summary(portfolio_payload, actions_payload)
    closed_positions = [
        item for item in portfolio.get("closed_items", []) if isinstance(item, dict)
    ]
    action_counts = count_values(market_rows, "action")
    reason_counts = count_values((row for row in market_rows if str(row.get("action") or "") == "skipped"), "reason")

    lines: list[str] = ["PolySentimentTrader Performance Replay", ""]
    lines.extend(
        [
            "Portfolio",
            f"- Cash: {fmt_money(portfolio.get('cash'))}",
            f"- Estimated equity: {fmt_money(portfolio.get('equity'))}",
            f"- Open positions: {portfolio.get('open_positions', 'n/a')}",
            f"- Closed positions: {portfolio.get('closed_positions', 'n/a')}",
            f"- Realized PnL: {fmt_money(portfolio.get('realized_pnl'))}",
            f"- Updated at: {portfolio.get('updated_at') or 'n/a'}",
            "",
            "Closed Trade Diagnostics",
        ]
    )
    lines.extend(summarize_closed_positions(closed_positions, strategy))

    lines.extend(["", "Candidate Funnel", f"- Considered rows: {len(market_rows)}"])
    lines.append(
        "- Actions: "
        + (", ".join(f"{key}={value}" for key, value in action_counts.most_common()) or "none")
    )
    lines.append(
        "- Skip reasons: "
        + (", ".join(f"{key}={value}" for key, value in reason_counts.most_common()) or "none")
    )

    lines.extend(["", "Threshold Pressure"])
    lines.extend(threshold_pressure(market_rows, strategy))

    lines.extend(["", "Near Misses"])
    misses = near_misses(market_rows, near_miss_limit)
    if not misses:
        lines.append("- None with side/quote data in the current trace.")
    for row in misses:
        lines.append(
            "- "
            f"{row.get('ticker', 'n/a')} {row.get('side', 'n/a')} "
            f"reason={row.get('reason', 'unknown')} "
            f"quote={fmt_number(selected_quote(row))} "
            f"edge={fmt_number(row.get('edge'))} "
            f"conf={fmt_number(row.get('confidence'))} "
            f"evidence={fmt_number(row.get('evidence_quality_score'))} "
            f"liq={fmt_number(row.get('liquidity'), 0)} "
            f"mkt_trades={row.get('market_trade_count') or 'n/a'} "
            f"question={row.get('question') or 'n/a'}"
        )

    lines.extend(["", "Log Tail"])
    lines.extend(summarize_log_tail(log_lines))

    lines.extend(["", "Recommendations"])
    lines.extend(recommendations(market_rows, closed_positions, reason_counts, action_counts))

    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze latest PolySentimentTrader performance snapshots.")
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTIONS_PATH)
    parser.add_argument("--markets", type=Path, default=DEFAULT_MARKETS_PATH)
    parser.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO_PATH)
    parser.add_argument("--logpath-file", type=Path, default=DEFAULT_LOGPATH_FILE)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--near-misses", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    actions_payload = load_json(args.actions)
    portfolio_payload = load_json(args.portfolio)
    market_rows = load_markets(args.markets, actions_payload)
    log_path = args.log or load_log_path(args.logpath_file)
    log_lines = read_log_tail(log_path)
    print(
        render_analysis(
            actions_payload,
            market_rows,
            portfolio_payload,
            log_lines,
            near_miss_limit=max(0, args.near_misses),
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
