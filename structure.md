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
	factors/                   # research factor library
		__init__.py                # public factor library exports
		core.py                    # factor series computation
		repository.py              # factor definitions and repository
		signals.py                 # factor series converted into normalized research signals
	models/                    # model signal generators, shape config, and training framework
		__init__.py                # public model exports
		baseline.py                # baseline factor ensemble model signal
		config.py                  # model shape and training configuration
		training.py                # training dataset and baseline training scaffold
	reports/                  # generated local HTML reports, ignored by git
	trading/
		analysis.py              # generated analysis reports with factors, model signals, correlations, backtest, and charts
		broker.py                # dry-run broker and Jupiter CLI adapter
		cli.py                   # command-line interface
		config.py                # environment-backed and market-backed settings
		data.py                  # Pyth/Hermes, Jupiter Price API, history fetchers, and CSV helpers
		domain.py                # shared trading dataclasses and enums
		indicators.py            # EMA, RSI, ATR, rolling levels
		plotting.py              # Plotly price, signal, distribution, and correlation charts
		risk.py                  # trade caps, leverage, and position sizing
		signals.py               # normalized research signals and forward-return correlation helpers
		storage.py               # logs and persisted open-position state
		strategy.py              # medium-slow swing signal logic
```

The bot is intentionally layered so strategy, risk, backtest, and execution can be tested separately. Live perps execution is routed through the Jupiter CLI adapter because the public Jupiter Perps REST API docs are still marked work in progress.

