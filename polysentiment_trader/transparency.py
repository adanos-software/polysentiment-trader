"""Public-safe action and market trace exports."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from polysentiment_trader.engine import CandidateTrace, Exit, Order, Portfolio, Position, RunResult, StrategyConfig


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def build_actions_payload(
    run: RunResult,
    *,
    generated_at: datetime,
    base_url: str,
    mode: str,
    config: StrategyConfig,
    scan_limit: int,
    days: int,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at.replace(microsecond=0).isoformat(),
        "mode": mode,
        "dry_run": dry_run,
        "base_url": public_base_url(base_url),
        "scan": {
            "days": days,
            "scan_limit": scan_limit,
        },
        "strategy": strategy_payload(config),
        "decision_explainer": decision_explainer_payload(run.decision_explainer),
        "portfolio": portfolio_payload(run.portfolio),
        "actions": [order_payload(order) for order in run.orders],
        "exits": [exit_payload(exit_) for exit_ in run.exits],
        "open_positions": [position_payload(position) for position in run.portfolio.open_positions()],
        "closed_positions": [position_payload(position) for position in run.portfolio.closed_positions],
        "skipped_counts": run.rejection_counts(),
        "candidate_action_counts": trace_counts(run.considered_markets, "action"),
        "candidate_reason_counts": trace_counts(run.considered_markets, "reason"),
        "skipped": [trace_payload(trace) for trace in run.considered_markets if trace.action == "skipped"],
        "considered_markets_count": len(run.considered_markets),
        "considered_markets": [trace_payload(trace) for trace in run.considered_markets],
    }


def write_transparency_exports(
    *,
    actions_path: Path | None,
    markets_path: Path | None,
    run: RunResult,
    generated_at: datetime,
    base_url: str,
    mode: str,
    config: StrategyConfig,
    scan_limit: int,
    days: int,
    dry_run: bool,
) -> None:
    if actions_path is None and markets_path is None:
        return

    payload = build_actions_payload(
        run,
        generated_at=generated_at,
        base_url=base_url,
        mode=mode,
        config=config,
        scan_limit=scan_limit,
        days=days,
        dry_run=dry_run,
    )
    if actions_path is not None:
        atomic_write_json(actions_path, payload)
    if markets_path is not None:
        rows = [csv_trace_payload(trace) for trace in run.considered_markets]
        atomic_write_csv(markets_path, rows, market_trace_fieldnames())


def public_base_url(base_url: str) -> str:
    stripped = base_url.strip().rstrip("/")
    parsed = urlsplit(stripped)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))
    return stripped.split("?", 1)[0].split("#", 1)[0]


def strategy_payload(config: StrategyConfig) -> dict[str, Any]:
    return {
        "initial_bankroll": round(config.initial_bankroll, 2),
        "max_positions": config.max_positions,
        "max_position_pct": config.max_position_pct,
        "max_stake": round(config.max_stake, 2),
        "min_stake": round(config.min_stake, 2),
        "min_buzz_score": config.min_buzz_score,
        "min_stock_trade_count": config.min_stock_trade_count,
        "min_market_trade_count": config.min_market_trade_count,
        "min_liquidity": config.min_liquidity,
        "min_abs_sentiment": config.min_abs_sentiment,
        "min_edge": config.min_edge,
        "min_evidence_quality_score": config.min_evidence_quality_score,
        "min_price": config.min_price,
        "max_price": config.max_price,
        "kelly_fraction": config.kelly_fraction,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "take_profit_cooldown_minutes": config.take_profit_cooldown_minutes,
        "max_stop_losses_per_day": config.max_stop_losses_per_day,
        "allow_stable_trend": config.allow_stable_trend,
        "require_clob_token_ids": config.require_clob_token_ids,
    }


def portfolio_payload(portfolio: Portfolio) -> dict[str, Any]:
    return {
        "initial_bankroll": round(portfolio.initial_bankroll, 2),
        "cash": round(portfolio.cash, 2),
        "market_value": round(sum(position.market_value for position in portfolio.open_positions()), 2),
        "equity": round(portfolio.equity(), 2),
        "exposure": round(portfolio.exposure(), 2),
        "open_positions": len(portfolio.open_positions()),
        "closed_positions": len(portfolio.closed_positions),
        "realized_pnl": round(
            sum(position.realized_pnl or 0.0 for position in portfolio.closed_positions),
            2,
        ),
        "updated_at": portfolio.updated_at,
    }


def order_payload(order: Order) -> dict[str, Any]:
    return {
        "action": "open_position",
        "ticker": order.ticker,
        "condition_id": order.condition_id,
        "question": order.question,
        "side": order.side,
        "price": round(order.price, 4),
        "stake": round(order.stake, 2),
        "shares": round(order.shares, 6),
        "estimated_probability": round(order.estimated_probability, 4),
        "edge": round(order.edge, 4),
        "confidence": round(order.confidence, 4),
        "evidence_quality_score": round(order.evidence_quality_score, 4),
        "reason": order.thesis,
        "counter_case": list(order.counter_case),
    }


def exit_payload(exit_: Exit) -> dict[str, Any]:
    return {
        "action": "close_position",
        "ticker": exit_.ticker,
        "condition_id": exit_.condition_id,
        "side": exit_.side,
        "entry_price": round(exit_.entry_price, 4),
        "exit_price": round(exit_.exit_price, 4),
        "stake": round(exit_.stake, 2),
        "pnl": round(exit_.pnl, 2),
        "return_pct": round(exit_.return_pct, 4),
        "reason": exit_.reason,
    }


def position_payload(position: Position) -> dict[str, Any]:
    payload = position.to_dict()
    payload["market_value"] = round(position.market_value, 2)
    payload["return_pct"] = round(position.return_pct, 4)
    return payload


def trace_payload(trace: CandidateTrace) -> dict[str, Any]:
    payload = asdict(trace)
    for key in (
        "quote",
        "estimated_probability",
        "edge",
        "confidence",
        "evidence_quality_score",
        "buzz_score",
        "sentiment_score",
        "liquidity",
        "volume_24h",
    ):
        if payload.get(key) is not None:
            payload[key] = round(float(payload[key]), 4)
    if payload.get("stake") is not None:
        payload["stake"] = round(float(payload["stake"]), 2)
    if payload.get("yes_price") is not None:
        payload["yes_price"] = round(float(payload["yes_price"]), 4)
    if payload.get("no_price") is not None:
        payload["no_price"] = round(float(payload["no_price"]), 4)
    return payload


def csv_trace_payload(trace: CandidateTrace) -> dict[str, Any]:
    payload = trace_payload(trace)
    payload["counter_case"] = " | ".join(payload.get("counter_case") or [])
    return payload


def decision_explainer_payload(explainer: Any) -> dict[str, Any]:
    return {
        "posture": explainer.posture,
        "summary": explainer.summary,
        "rationale": list(explainer.rationale),
    }


def trace_counts(traces: list[CandidateTrace], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trace in traces:
        value = getattr(trace, field)
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def market_trace_fieldnames() -> list[str]:
    return [
        "ticker",
        "condition_id",
        "question",
        "action",
        "reason",
        "detail",
        "side",
        "quote",
        "estimated_probability",
        "edge",
        "confidence",
        "evidence_quality_score",
        "stake",
        "counter_case",
        "buzz_score",
        "sentiment_score",
        "trend",
        "market_type",
        "liquidity",
        "volume_24h",
        "market_trade_count",
        "yes_price",
        "no_price",
        "end_date",
    ]
