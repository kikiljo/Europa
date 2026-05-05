# Project Structure

```text
Europa/
	README.md                  # setup, commands, and safety notes
	pyproject.toml             # Python package metadata and CLI entry point
	.env.example               # optional runtime configuration
	backtest/
		engine.py                # candle-by-candle backtest engine
	config/
		markets.json             # Jupiter Perps market definitions, candle intervals, Pyth feed ids, and fallback symbols
	data/
		README.md                # data folder overview
		SCHEMA.md                # marketdata.v1 CSV and metadata contract
	trading/
		broker.py                # dry-run broker and Jupiter CLI adapter
		cli.py                   # command-line interface
		config.py                # environment-backed and market-backed settings
		data.py                  # Pyth/Hermes, Jupiter Price API, history fetchers, and CSV helpers
		factors.py               # reusable factor series and latest factor snapshots
		indicators.py            # EMA, RSI, ATR, rolling levels
		models.py                # shared dataclasses and enums
		plotting.py              # Plotly mid-price chart generation
		risk.py                  # trade caps, leverage, and position sizing
		storage.py               # logs and persisted open-position state
		strategy.py              # medium-slow swing signal logic
```

The bot is intentionally layered so strategy, risk, backtest, and execution can be tested separately. Live perps execution is routed through the Jupiter CLI adapter because the public Jupiter Perps REST API docs are still marked work in progress.

