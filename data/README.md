# Data Folder

The canonical data contract is defined in `SCHEMA.md` as `marketdata.v1`.

CSV candles use this schema:

```csv
ts,open,high,low,close,volume
2026-05-05T18:30:00+00:00,85.70,85.90,85.58,85.89,22046.80
```

Every canonical CSV also has a sidecar metadata file named `<dataset>.meta.json` with `schema=marketdata.v1`, market identity, interval, source, time range, row count, and basic quality fields such as `expected_count` and `missing_count`.

The live sampler updates one candle bucket at a time using the same schema as historical fetches, so backtests and live decisions consume identical input files.
