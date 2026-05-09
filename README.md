# Europa - Jupiter Perps Research and Runtime

Europa is a Jupiter Perps trading project with two deliberately separate halves:

- Research: market data, factors, model signals, backtests, analysis reports, and model-training scaffolds.
- Runtime: a live trading executor boundary for market parsing, inference, risk, gateway behavior, order submission, position sync, and state updates.

The default strategy is still slow-to-medium frequency: 15-30 minute sampling, swing entries, explicit risk sizing, and a target of roughly 10 trades per week. The architecture is intentionally broader than one SOL strategy, so we can add markets, factors, models, and faster executor implementations without rewriting the research stack.

Important: Jupiter's public Perps REST API documentation is still marked work in progress. This project uses Pyth/Hermes prices for mark-price sampling by default and currently routes perps execution through the Jupiter CLI adapter. The default runtime mode is dry-run/paper trading.

## Run Modes

Paper run means simulated trading. The runtime computes the same signal, risk decision, order intent, and state update path, but the order is accepted by the local dry-run broker instead of being sent to Jupiter. It is useful for checking logs, sizing, state files, and executor behavior before live trading.

Live run means the bot is allowed to send orders through the configured Jupiter CLI gateway. Use it only after reviewing paper logs and backtest behavior.

```powershell
python -m trading run-once --market SOL --paper
python -m trading run-once --market SOL --live
```

## Architecture

```text
data/market feed -> factors -> models -> strategy/inference -> algo/risk -> gateway -> venue/API
```

Repository layout:

- `factors/`: reusable factor library and factor signal conversion.
- `models/`: model shape config, model signal generators, and training dataset scaffolding.
- `backtest/`: local candle-by-candle simulation.
- `trading/`: live runtime boundary and operational tooling.
- `data/`: canonical market data docs and local generated datasets.
- `reports/`: generated local HTML reports.

The important boundary is `trading/`. Research can remain Python-heavy because iteration speed matters there. Runtime performance work should happen around `trading/executor.py`, `trading/gateway.py`, network retries, submission behavior, position sync, and state handling. If we later replace the executor with Rust, C++, or Go, the replacement should preserve the order-intent and execution-report contracts instead of changing factors or models.

## Runtime Flow

The current live executor is Python, but its modules are shaped like a future high-performance runtime:

- `trading/parser.py`: parse real-time market payloads into normalized market events.
- `trading/inference.py`: run lightweight factor/model/strategy inference.
- `trading/algo.py`: turn signals into risk-checked order decisions.
- `trading/gateway.py`: translate local decisions into venue/API behavior.
- `trading/executor.py`: orchestrate inference, risk, gateway execution, trade logs, and state updates.
- `trading/broker.py`: current dry-run and Jupiter CLI broker adapters.

For Jupiter Perps, the likely performance bottleneck is network and venue behavior rather than local CPU: RPC/API latency, retries, signing, submission, confirmation, position sync, and failure recovery.

## Setup

```powershell
cd "c:\Users\Ou138\Desktop\crypto trading\Europa"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Install Jupiter CLI if you want the execution adapter:

```powershell
npm i -g @jup-ag/cli
jup keys add mykey
```

Copy `.env.example` to `.env` if you want local environment variables. Market defaults live in `config/markets.json`; current configured markets are `SOL`, `BTC`, and `ETH`.

## Market Data

Fetch 200 days of canonical SOL history:

```powershell
python -m trading fetch-history-range --market SOL --days 200
```

The interval comes from `config/markets.json` unless `--interval` is provided. The default deep-history source is Pyth Benchmarks using the configured Pyth symbol/feed for the selected Jupiter Perps market.

Collect one live price sample into the same canonical CSV:

```powershell
python -m trading collect-once --market SOL
```

Canonical CSV schema:

```csv
ts,open,high,low,close,volume
2026-05-05T18:30:00+00:00,85.7000000000,85.9000000000,85.5800000000,85.8900000000,0.0000000000
```

Each CSV has a `<dataset>.meta.json` sidecar. The full schema is in `data/SCHEMA.md`.

## Research Workflow

Run a backtest:

```powershell
python -m trading backtest --market SOL
```

Inspect the latest strategy signal:

```powershell
python -m trading signal --market SOL
```

Write an interactive mid-price chart:

```powershell
python -m trading plot --market SOL
```

Generate a factor signal analysis report with processed factor snapshots, live-safe expanding-normalized signals, 1-240 tick tail-only correlation/decay, price-equivalent cost curves, and simplified top/bottom tail-event analysis:

```powershell
python -m trading analyze --market SOL
```

Customize report horizons, factor signals, the cost curve, and top/bottom tail size:

```powershell
python -m trading analyze --market SOL --horizons 1-240 --factor-signals fast_ema_slope,slow_ema_slope,ema_spread,price_vs_slow_ema,rsi_momentum,rsi_reversion,rsi_slope --hourly-cost-bps 0.10 --tail-fraction 0.01
```

Run the same analysis on 5 minute and 15 minute candles after fetching fresh datasets:

```powershell
python -m trading fetch-history-range --market SOL --interval 5m --out data/sol_usd_5m.csv --days 200
python -m trading fetch-history-range --market SOL --interval 15m --out data/sol_usd_15m.csv --days 200
python -m trading analyze --market SOL --interval 5m --horizons 1-240
python -m trading analyze --market SOL --interval 15m --horizons 1-240
```

Build the baseline model training dataset and print the training scaffold summary:

```powershell
python -m trading train-model --market SOL --target-horizon 4
```

Reports are written under `reports/` and ignored by git.

## Strategy Defaults

- Candle interval: configured per market in `config/markets.json` as `candle_interval`.
- Signal style: EMA trend filter plus Donchian breakout confirmation.
- Risk style: ATR-based stop, ATR-based take profit, risk-per-trade sizing.
- Trade throttle: weekly trade cap defaults to 10.
- Leverage: default 2x, hard cap defaults to 3x.

The default market configs use `30m`, intentionally slower than a scalper. A 15 minute interval can work, but it will usually produce more noise and fees. Compare intervals in backtests before live use.

## Deployment

You do not need a dedicated server on day one. Start locally in paper mode so logs, state files, order intents, and report outputs are easy to inspect.

Recommended path:

1. Local research machine: fetch data, backtest, generate reports, train/check model shapes, and run paper trades.
2. Small VPS or always-on machine: run the live executor loop, hold runtime state, query positions, submit orders, and write trade logs.
3. Separate executor service: consider this only when network reliability, parallel venues, lower jitter, or stricter uptime becomes important.

For unattended live trading, a VPS or dedicated always-on machine is useful mainly for uptime and stable networking, not raw CPU speed.

## Adding Markets

Add a new Jupiter Perps market in `config/markets.json` with:

- Jupiter CLI asset name.
- `candle_interval`.
- Pyth symbol and feed id.
- Default data path.
- Fallback Coinbase/Kraken/Binance symbols if needed.

Then run:

```powershell
python -m trading fetch-history-range --market BTC --days 200
python -m trading backtest --market BTC
```

## Safety Notes

- Keep `JUPITER_DRY_RUN=true` until paper logs and backtests look sane.
- Use USDC collateral first; sizing is easier to audit.
- Start with tiny size if live trading is enabled.
- Perps can liquidate fast during crypto volatility. The defaults are conservative but not a guarantee of safety.
- Pyth Benchmarks are preferred for Jupiter Perps history. CEX history commands are convenient research proxies and can differ from oracle-driven execution.
- Verify every new market's Pyth feed id and Hermes latest price before relying on it.

## File Map

- `config/markets.json`: market definitions, intervals, Pyth feed ids, and fallback symbols.
- `factors/`: factor series, factor definitions, and normalized factor signals.
- `models/`: model signal generators, shape config, training config, and training dataset builder.
- `backtest/engine.py`: local candle-by-candle backtest engine.
- `trading/domain.py`: shared trading dataclasses and enums.
- `trading/executor.py`: live runtime executor orchestration.
- `trading/gateway.py`: gateway boundary to venue/API behavior.
- `trading/parser.py`: real-time market parser interfaces.
- `trading/inference.py`: live inference over strategy factors and model signals.
- `trading/algo.py`: risk-checked order-decision layer.
- `trading/broker.py`: dry-run and Jupiter CLI adapters.
- `trading/data.py`: Pyth/Hermes sampling, history fetchers, and canonical CSV helpers.
- `trading/analysis.py`: HTML analysis reports.
- `trading/plotting.py`: Plotly charts.
- `trading/risk.py`: leverage, trade caps, and sizing.
- `trading/storage.py`: trade logs and persisted open-position state.
- `trading/strategy.py`: current swing strategy logic.