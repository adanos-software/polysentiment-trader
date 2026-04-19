# PolySentimentTrader

Polymarket paper trading demo bot powered by [Adanos](https://adanos.org) Polymarket sentiment data.

PolySentimentTrader turns prediction-market sentiment signals into simulated YES/NO trades. It is built as a public, walletless demo for showing how Adanos data can drive actionable trading workflows without risking real funds.

## What It Does

- Reads production Adanos Polymarket endpoints from `https://api.adanos.org`.
- Scans trending stock and ETF markets.
- Converts Adanos sentiment, buzz, flow, liquidity, and prices into trade candidates.
- Simulates YES/NO entries in a local JSON paper ledger.
- Marks open positions to the latest API prices on each run.
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
- `top_mentions[].yes_price`
- `top_mentions[].no_price`
- `top_mentions[].liquidity`
- `top_mentions[].trade_count`

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

The default ledger path is:

```text
data/paper-portfolio.json
```

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
2. Rejects weak candidates with low buzz, low trade count, weak sentiment, falling flow, or low liquidity.
3. Infers whether a market's YES outcome is bullish or bearish for the ticker.
4. Chooses YES or NO based on Adanos directional sentiment.
5. Estimates a simple model probability from sentiment, trend, buzz, liquidity, and market flow.
6. Computes edge as `estimated_probability - current_price`.
7. Sizes the position using fractional Kelly with hard caps.
8. Saves the simulated position to the paper ledger.

Open positions are refreshed on later runs. Positions close automatically in the paper ledger when they hit the configured stop-loss or take-profit threshold.

## Useful Options

```bash
polysentiment-trader --scan-limit 50
polysentiment-trader --min-edge 0.005 --max-stake 50
polysentiment-trader --bankroll 250 --max-stake 10
polysentiment-trader --ledger data/demo-portfolio.json
```

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

- Action recommendation export, e.g. `data/latest-actions.json`.
- Manual approval mode for proposed trades.
- Execution adapter interface for future live trading.
- Optional Polymarket CLOB adapter behind explicit live-trading flags.
- Dashboard or static report for marketing demos.

## Disclaimer

This project is for demonstration and research workflows. It is not financial advice, and it does not guarantee trading performance.
