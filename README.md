# Europa - A Jupiter SOL Perps Slow Trader

This is a conservative Python scaffold for a medium-slow SOL perpetuals strategy on Jupiter.
It is designed for 15-30 minute candles, swing entries, explicit risk sizing, and roughly 10 trades per week.

Important: Jupiter's public Perps REST API documentation is still marked work in progress. This project uses Jupiter's Price API for live SOL pricing and provides a Jupiter CLI execution adapter for perps. The default mode is dry-run/paper trading. Review the generated orders, run backtests, and start with tiny size before enabling live execution.

## Strategy Shape

- Default candle interval: `30m`.
- Signal style: EMA trend filter plus Donchian breakout confirmation.
- Risk style: ATR-based stop, ATR-based take profit, risk-per-trade sizing.
- Trade throttle: weekly trade cap defaults to 10.
- Leverage: default 2x, hard cap defaults to 3x.

The default is intentionally slower than a scalper. A 15 minute interval can work, but it will usually produce more noise and more fees. Start with 30 minutes, then compare 15m vs 30m in backtests.

## Setup

```powershell
cd "c:\Users\Ou138\Desktop\crypto trading\jupiter_sol_perps_slow_trader"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Install Jupiter CLI if you want the execution adapter:

```powershell
npm i -g @jup-ag/cli
jup keys add mykey
```

Copy `.env.example` to `.env` if you want local environment variables. The CLI also accepts flags, so `.env` is optional.

## Common Commands

Collect one live SOL price sample from Jupiter Price API and update a candle CSV. If `api.jup.ag` rejects keyless access, set `JUPITER_API_KEY` or `JUPITER_BASE_URL=https://lite-api.jup.ag`:

```powershell
python -m trading collect-once --out data/sol_usd_30m.csv
```

Fetch spot SOL/USD candles from Kraken for rough strategy research:

```powershell
python -m trading fetch-history --out data/sol_usd_30m_history.csv --interval 30m --limit 500
```

Run a backtest:

```powershell
python -m trading backtest --data data/sol_usdt_30m.csv
```

Inspect the latest signal:

```powershell
python -m trading signal --data data/sol_usdt_30m.csv
```

Run one trading decision in paper mode:

```powershell
python -m trading run-once --data data/sol_usd_30m.csv
```

Run one decision against Jupiter CLI live execution:

```powershell
python -m trading run-once --data data/sol_usd_30m.csv --live
```

`--live` disables the bot-level dry-run flag. Jupiter CLI can still be configured separately, and this project will refuse live orders below the configured risk checks.

## Files

- `trading/config.py`: environment-backed configuration.
- `trading/data.py`: Jupiter Price API sampling and CSV candle utilities.
- `trading/indicators.py`: EMA, RSI, ATR, and rolling breakout helpers.
- `trading/strategy.py`: medium-slow swing signal logic.
- `trading/risk.py`: weekly caps, daily loss guard, leverage, and size calculation.
- `trading/broker.py`: dry-run broker and Jupiter CLI perps adapter.
- `backtest/engine.py`: simple candle-by-candle backtest engine.

## Safety Notes

- Keep `JUPITER_DRY_RUN=true` until you have reviewed logs and backtest behavior.
- Use USDC collateral first. It makes sizing easier to audit.
- Perps can liquidate fast during SOL volatility. The defaults use modest leverage, but they are not a guarantee of safety.
- The Kraken/Binance history command is only a convenient research proxy. Live execution uses Jupiter pricing/execution and will differ.
