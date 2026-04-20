# PolySentimentTrader

Polymarket paper trading demo bot powered by [Adanos](https://adanos.org) Polymarket sentiment data.

PolySentimentTrader turns prediction-market sentiment signals into simulated YES/NO trades. It is built as a public, walletless demo for showing how Adanos data can drive actionable trading workflows without risking real funds.

## What It Does

- Reads production Adanos Polymarket endpoints from `https://api.adanos.org`.
- Scans trending stock and ETF markets.
- Converts Adanos sentiment, buzz, flow, liquidity, and prices into trade candidates.
- Simulates YES/NO entries in a local JSON paper ledger.
- Marks open positions to the latest API prices on each run.
- Writes public-safe transparency exports for the latest run.
- Applies conservative risk rules: max positions, max stake, stop-loss, take-profit, and minimum edge.
- Supports one-shot runs and scheduled loops.

## Safety Model

This repository is paper trading only.

- No wallet connection.
- No private keys.
- No real Polymarket orders.
- No funds are moved.
- `.env` and paper ledgers are ignored by git.

The code is structured so a real execution adapter can be added later, but the current release only writes simulated positions.

## Data Source

The bot uses protected Adanos API endpoints:

```text
GET /polymarket/stocks/v1/trending
GET /polymarket/stocks/v1/stock/{ticker}
```

Signals consumed by the strategy:

- `buzz_score`
- `trend`
- `trade_count`
- `sentiment_score`
- `top_mentions[].condition_id`
- `top_mentions[].end_date`
- `top_mentions[].yes_price`
- `top_mentions[].no_price`
- `top_mentions[].liquidity`
- `top_mentions[].trade_count`
- optional CLOB token metadata such as `clob_token_ids`, `outcomes`, or token objects when available

## Quick Start

```bash
git clone https://github.com/adanos-software/polysentiment-trader.git
cd polysentiment-trader
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
ADANOS_BASE_URL=https://api.adanos.org
ADANOS_API_KEY=your_adanos_api_key_here
```

Never commit `.env`.

## Run

Preview without writing a ledger:

```bash
polysentiment-trader --no-write
```

Run one paper trading cycle and write the ledger:

```bash
polysentiment-trader
```

Run every hour:

```bash
polysentiment-trader --loop --interval-minutes 60
```

Run three one-minute cycles for a quick smoke test:

```bash
polysentiment-trader --loop --interval-minutes 1 --cycles 3
```

In loop mode, a failed API cycle is logged and skipped; the next cycle continues after the configured interval. One-shot runs still fail fast so setup and API issues are visible.

The default ledger path is:

```text
data/paper-portfolio.json
```

The latest run also writes two local transparency files:

```text
data/latest-actions.json
data/considered-markets-latest.csv
```

These files are ignored by git. They contain no API key, wallet secret, or private Polymarket credential.

## Make Commands

```bash
make setup      # create/update venv and install package
make preview    # dry run, no ledger write
make run        # one papertrade cycle
make test-run   # three one-minute cycles
make loop       # hourly loop
make portfolio  # pretty-print the JSON ledger
make test       # unit tests
```

Demo-friendly tuning:

```bash
make demo SCAN_LIMIT=50 MIN_EDGE=0.005 MAX_STAKE=50
```

## Strategy

For each trending ticker, the bot:

1. Loads the ticker's detailed Polymarket market list.
2. Normalizes market metadata and rejects stale, closed, malformed, or incomplete market payloads.
3. Rejects weak candidates with low buzz, low trade count, weak sentiment, falling flow, or low liquidity.
4. Infers whether a market's YES outcome is bullish or bearish for the ticker.
5. Chooses YES or NO based on Adanos directional sentiment.
6. Reads the selected side through a quote adapter instead of touching raw API fields directly.
7. Estimates a simple model probability from sentiment, trend, buzz, liquidity, and market flow.
8. Computes edge as `estimated_probability - current_price`.
9. Sizes the position using fractional Kelly with hard caps.
10. Saves the simulated position to the paper ledger.

Open positions are refreshed on later runs. Positions close automatically in the paper ledger when they hit the configured stop-loss or take-profit threshold.

## Transparency Exports

Every run emits a public-safe snapshot for demos and debugging:

- `data/latest-actions.json` gives the latest portfolio summary, strategy thresholds, new entries, exits, open positions, closed positions, skip counts, and the detailed candidate trace.
- `data/considered-markets-latest.csv` gives one row per traced candidate market with ticker, condition id, question, action, skip reason, quote, model probability, edge, liquidity, flow, prices, and end date.

The trace records both successful entries and rejected candidates. It also explains stock-level skips such as weak sentiment, already-open positions, or full portfolio capacity against the available market rows when market metadata exists.
In the JSON, `skipped_counts` counts strategy decisions, while `candidate_reason_counts` counts rows in the detailed trace.

## Data Quality

The bot fails closed when market data is not usable. Candidate markets are skipped before strategy scoring when they are:

- missing a `condition_id` or question
- inactive, closed, archived, or past `end_date`
- carrying invalid probability prices outside `0..1`
- carrying invalid negative liquidity, volume, or trade counts
- missing YES/NO CLOB token ids when token ids are explicitly required by future execution modes

The current paper mode does not require CLOB token ids. It still parses them when the API provides `tokens`, `outcomes` plus `clob_token_ids`, or compatible camelCase variants. Future live/approval modes can enable strict token-id requirements without changing the scoring engine.

## Useful Options

```bash
polysentiment-trader --scan-limit 50
polysentiment-trader --min-edge 0.005 --max-stake 50
polysentiment-trader --bankroll 250 --max-stake 10
polysentiment-trader --ledger data/demo-portfolio.json
polysentiment-trader --actions-out data/demo-actions.json
polysentiment-trader --markets-out data/demo-markets.csv
polysentiment-trader --actions-out none --markets-out none
polysentiment-trader --require-clob-token-ids --no-write
```

The export paths can also be configured with `POLYSENTIMENT_ACTIONS_OUT` and `POLYSENTIMENT_MARKETS_OUT`.

## Development

```bash
make setup-dev
make test
```

Run the CLI directly from source:

```bash
python -m polysentiment_trader.cli --no-write
```

## Roadmap

- Manual approval mode for proposed trades.
- Execution adapter interface for future live trading.
- Optional Polymarket CLOB adapter behind explicit live-trading flags.
- Dashboard or static report for marketing demos.

## Disclaimer

This project is for demonstration and research workflows. It is not financial advice, and it does not guarantee trading performance.
