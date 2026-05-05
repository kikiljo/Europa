# Data Folder

CSV candles use this schema:

```csv
timestamp,open,high,low,close,volume
2026-05-01T00:00:00+00:00,130.0,131.2,129.7,130.8,0
```

The live sampler updates one candle bucket at a time. For backtests, prefer real OHLCV candle history over single-price samples.
