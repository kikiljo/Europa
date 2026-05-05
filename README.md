# Europa - A Jupiter Perps Slow Trader

This is a conservative Python scaffold for medium-slow perpetuals strategies on Jupiter Perps.
It is designed for 15-30 minute candles, swing entries, explicit risk sizing, and roughly 10 trades per week.

Important: Jupiter's public Perps REST API documentation is still marked work in progress. This project uses Pyth/Hermes prices for live mark-price sampling by default and provides a Jupiter CLI execution adapter for perps. The default mode is dry-run/paper trading. Review the generated orders, run backtests, and start with tiny size before enabling live execution.

## Strategy Shape

- Default candle interval: configured per market in `config/markets.json` as `candle_interval`.
- Signal style: EMA trend filter plus Donchian breakout confirmation.
- Risk style: ATR-based stop, ATR-based take profit, risk-per-trade sizing.
- Trade throttle: weekly trade cap defaults to 10.
- Leverage: default 2x, hard cap defaults to 3x.

The default market configs use `30m`, which is intentionally slower than a scalper. A 15 minute interval can work, but it will usually produce more noise and more fees. Start with 30 minutes, then compare 15m vs 30m in backtests by changing `candle_interval` or passing `--interval` as a one-off override.

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

Copy `.env.example` to `.env` if you want local environment variables. Market defaults live in `config/markets.json`, including each market's `candle_interval`. The configured Jupiter Perps markets are `SOL`, `BTC`, and `ETH`.

## Common Commands

Fetch 200 days of canonical SOL history. The interval comes from `config/markets.json` unless `--interval` is provided. The default deep-history source is Pyth Benchmarks, using the configured Pyth symbol/feed for the selected Jupiter Perps market:

```powershell
python -m trading fetch-history-range --market SOL --days 200
```

Run a backtest with the configured market's default data path:

```powershell
python -m trading backtest --market SOL
```

Inspect the latest signal:

```powershell
python -m trading signal --market SOL
```

Write an interactive Plotly chart with candlesticks, derived mid price, EMA overlays, and range width:

```powershell
python -m trading plot --market SOL
```

The chart is written to `reports/sol_mid_price.html` by default. With the current OHLCV schema, `mid` is derived as `(high + low) / 2`; true bid/ask midpoint would require storing bid and ask fields in a future schema version.

Collect one live price sample from the market's configured source and update the same canonical candle CSV. The default configured source is Pyth/Hermes:

```powershell
python -m trading collect-once --market SOL
```

Run one trading decision in paper mode:

```powershell
python -m trading run-once --market SOL
```

Run one decision against Jupiter CLI live execution:

```powershell
python -m trading run-once --market SOL --live
```

`--live` disables the bot-level dry-run flag. Jupiter CLI can still be configured separately, and this project will refuse live orders below the configured risk checks.

Use another Jupiter Perps market by switching the market key:

```powershell
python -m trading fetch-history-range --market BTC --days 200
python -m trading backtest --market BTC
```

To add a new market, extend `config/markets.json` with the Jupiter CLI asset name, `candle_interval`, Pyth symbol/feed id, default data path, and fallback history-source symbols. Keep `price_mint` only if you want Jupiter Price API as a fallback source.

## Data Format

Historical and live data use the same canonical schema. The full definition is in `data/SCHEMA.md`:

```csv
ts,open,high,low,close,volume
2026-05-05T18:30:00+00:00,85.7000000000,85.9000000000,85.5800000000,85.8900000000,22046.8040912400
```

Each CSV has a sidecar metadata file named `<dataset>.meta.json` with `schema=marketdata.v1`, `symbol`, `instrument`, `venue`, `interval_minutes`, `source`, `first_ts`, `last_ts`, `count`, and `extras` for fields such as `pyth_price_id`, `expected_count`, and `missing_count`.

## Files

- `config/markets.json`: market definitions for Jupiter Perps assets, candle intervals, Pyth feed ids, and fallback history-source symbols.
- `trading/config.py`: environment-backed and market-backed configuration.
- `trading/data.py`: Pyth/Hermes and Jupiter Price API sampling, Coinbase/Kraken/Binance/Pyth history fetchers, and canonical CSV utilities.
- `trading/plotting.py`: Plotly HTML charts for mid price, candles, EMAs, and candle range.
- `trading/indicators.py`: low-level EMA, RSI, ATR, and rolling breakout helpers.
- `trading/factors.py`: reusable factor library that turns candles into factor series and latest snapshots.
- `trading/strategy.py`: medium-slow swing signal logic built from the factor library.
- `trading/risk.py`: weekly caps, daily loss guard, leverage, and size calculation.
- `trading/broker.py`: dry-run broker and Jupiter CLI perps adapter.
- `backtest/engine.py`: simple candle-by-candle backtest engine.

## Safety Notes

- Keep `JUPITER_DRY_RUN=true` until you have reviewed logs and backtest behavior.
- Use USDC collateral first. It makes sizing easier to audit.
- Perps can liquidate fast during crypto volatility. The defaults use modest leverage, but they are not a guarantee of safety.
- Pyth Benchmarks are the preferred history source for Jupiter Perps. Coinbase/Kraken/Binance history commands are convenient research proxies and will differ from oracle-driven execution.
- Keep Pyth feed ids in `config/markets.json` and verify a new market's Hermes latest price before relying on it.
