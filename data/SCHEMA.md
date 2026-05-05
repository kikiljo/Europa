# marketdata.v1

`marketdata.v1` is the canonical OHLCV format used by both backtests and live sampling.

## CSV

File name is market-specific, for example `sol_usd_30m.csv`.

Required header:

```csv
ts,open,high,low,close,volume
```

Fields:

- `ts`: candle bucket start time, UTC ISO 8601 with timezone, for example `2026-05-05T19:00:00+00:00`.
- `open`: first price in the bucket.
- `high`: highest price in the bucket.
- `low`: lowest price in the bucket.
- `close`: last price in the bucket.
- `volume`: source volume if available; live oracle samples use `0.0`.

Numeric values are written as decimal strings with fixed precision. Consumers should parse them as floats or decimals.

## Sidecar Metadata

Every CSV must have a sidecar file next to it named `<dataset>.meta.json`.

Required fields:

```json
{
  "schema": "marketdata.v1",
  "symbol": "SOL/USD",
  "instrument": "SOL-PERP",
  "venue": "jupiter-perps",
  "interval_minutes": 30,
  "source": "pyth-benchmarks:Crypto.SOL/USD",
  "first_ts": "2025-10-17T19:30:00+00:00",
  "last_ts": "2026-05-05T19:00:00+00:00",
  "count": 9600,
  "generated_at": "2026-05-05T19:00:00+00:00",
  "notes": "paginated, requested_days=200; pyth_price_id=...",
  "extras": {
    "pyth_price_id": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "expected_count": 9600,
    "missing_count": 0
  }
}
```

Metadata fields:

- `schema`: must be `marketdata.v1`.
- `symbol`: logical market pair.
- `instrument`: target Jupiter Perps instrument.
- `venue`: target execution venue, currently `jupiter-perps`.
- `interval_minutes`: candle interval after aggregation. This normally comes from the selected market's `candle_interval` in `config/markets.json`, unless a CLI command overrides it with `--interval`.
- `source`: raw source and symbol/feed used to build the candles.
- `first_ts`, `last_ts`: inclusive UTC time range in the CSV.
- `count`: number of candle rows.
- `generated_at`: UTC timestamp when the file was written.
- `notes`: human-readable source notes.
- `extras`: source-specific machine-readable fields. For Pyth-backed data, include `pyth_price_id` when known. Writers also add `expected_count` and `missing_count` for basic gap accounting.

## Code Ownership

The executable definition lives in `trading/data.py`:

- `CANDLE_FIELDS`
- `MARKETDATA_SCHEMA`
- `DatasetMeta`
- `write_dataset`
- `load_dataset_meta`

The candle row serializer/parser lives in `trading/models.py` as `Candle.to_csv_row()` and `Candle.from_mapping()`.