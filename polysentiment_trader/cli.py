"""Command line runner for the Polymarket sentiment paper trader."""

from __future__ import annotations

import argparse
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from polysentiment_trader.client import AdanosClient
from polysentiment_trader.engine import (
    PaperTrader,
    StrategyConfig,
    format_report,
    load_portfolio,
    save_portfolio,
)
from polysentiment_trader.transparency import write_transparency_exports


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = PROJECT_ROOT / "data" / "paper-portfolio.json"
DEFAULT_ACTIONS = PROJECT_ROOT / "data" / "latest-actions.json"
DEFAULT_MARKETS = PROJECT_ROOT / "data" / "considered-markets-latest.csv"
DEFAULT_BASE_URL = "https://api.adanos.org"


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load simple KEY=VALUE pairs without overriding existing environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def run_once(args: argparse.Namespace) -> None:
    client = AdanosClient(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout,
    )
    config = StrategyConfig(
        initial_bankroll=args.bankroll,
        max_positions=args.max_positions,
        max_stake=args.max_stake,
        min_edge=args.min_edge,
        min_buzz_score=args.min_buzz_score,
        min_abs_sentiment=args.min_abs_sentiment,
        require_clob_token_ids=args.require_clob_token_ids,
    )
    ledger_path = Path(args.ledger).expanduser()
    actions_path = optional_path(args.actions_out)
    markets_path = optional_path(args.markets_out)
    portfolio = load_portfolio(ledger_path, initial_bankroll=args.bankroll)

    trending = client.get_polymarket_trending(days=args.days, limit=args.scan_limit)
    details = []
    for item in trending:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        detail = client.get_polymarket_stock(ticker, days=args.days)
        if detail:
            details.append(detail)

    run = PaperTrader(config).run(trending=trending, details=details, portfolio=portfolio)
    print(format_report(run))

    if args.no_write:
        print("\nLedger: not written (--no-write)")
    else:
        save_portfolio(ledger_path, portfolio)
        print(f"\nLedger: {ledger_path}")

    write_transparency_exports(
        actions_path=actions_path,
        markets_path=markets_path,
        run=run,
        generated_at=datetime.fromisoformat(run.portfolio.updated_at),
        base_url=args.base_url,
        mode="paper",
        config=config,
        scan_limit=args.scan_limit,
        days=args.days,
        dry_run=args.no_write,
    )

    if actions_path is not None:
        print(f"Actions: {actions_path}")
    if markets_path is not None:
        print(f"Markets: {markets_path}")


def optional_path(raw_path: str) -> Path | None:
    if raw_path.strip().lower() in {"", "none", "off", "false", "0"}:
        return None
    return Path(raw_path).expanduser()


def build_parser() -> argparse.ArgumentParser:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Papertrade Polymarket contracts with Adanos sentiment data.",
    )
    parser.add_argument("--base-url", default=os.getenv("ADANOS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.getenv("ADANOS_API_KEY"))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--actions-out", default=os.getenv("POLYSENTIMENT_ACTIONS_OUT", str(DEFAULT_ACTIONS)))
    parser.add_argument("--markets-out", default=os.getenv("POLYSENTIMENT_MARKETS_OUT", str(DEFAULT_MARKETS)))
    parser.add_argument("--bankroll", type=float, default=1000.0)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--scan-limit", type=int, default=25)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--max-stake", type=float, default=25.0)
    parser.add_argument("--min-edge", type=float, default=0.015)
    parser.add_argument("--min-buzz-score", type=float, default=40.0)
    parser.add_argument("--min-abs-sentiment", type=float, default=0.12)
    parser.add_argument(
        "--require-clob-token-ids",
        action="store_true",
        help="Skip markets without YES/NO CLOB token ids; useful for future execution adapters.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval-minutes", type=float, default=60.0)
    parser.add_argument("--cycles", type=int, default=0, help="Stop after N cycles in loop mode; 0 means forever")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.api_key:
        parser.error("Set ADANOS_API_KEY or pass --api-key; Polymarket endpoints are protected.")

    if not args.loop:
        run_once(args)
        return

    run_loop(args)


def run_loop(args: argparse.Namespace, run_cycle=run_once, sleep=time.sleep) -> None:
    cycles = 0
    while True:
        cycles += 1
        print(f"\nCycle {cycles}")
        try:
            run_cycle(args)
        except Exception:
            print(f"\nCycle {cycles} failed; skipping until next interval.")
            traceback.print_exc()
        if args.cycles and cycles >= args.cycles:
            return
        sleep(max(args.interval_minutes, 0.1) * 60)


if __name__ == "__main__":
    main()
