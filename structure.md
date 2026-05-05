# Project Structure

```text
jupiter_sol_perps_slow_trader/
	README.md                  # setup, commands, and safety notes
	pyproject.toml             # Python package metadata and CLI entry point
	.env.example               # optional runtime configuration
	backtest/
		engine.py                # candle-by-candle backtest engine
	data/
		README.md                # candle CSV schema
	trading/
		broker.py                # dry-run broker and Jupiter CLI adapter
		cli.py                   # command-line interface
		config.py                # environment-backed settings
		data.py                  # Jupiter Price API and CSV candle helpers
		indicators.py            # EMA, RSI, ATR, rolling levels
		models.py                # shared dataclasses and enums
		risk.py                  # trade caps, leverage, and position sizing
		storage.py               # logs and persisted open-position state
		strategy.py              # medium-slow SOL swing signal logic
```

The bot is intentionally layered so strategy, risk, backtest, and execution can be tested separately. Live perps execution is routed through the Jupiter CLI adapter because the public Jupiter Perps REST API docs are still marked work in progress.

