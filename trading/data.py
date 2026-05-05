from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading.config import WRAPPED_SOL_MINT
from trading.domain import Candle


CANDLE_FIELDS = ["ts", "open", "high", "low", "close", "volume"]
MARKETDATA_SCHEMA = "marketdata.v1"


class DataError(RuntimeError):
    pass


@dataclass
class DatasetMeta:
    """Sidecar metadata describing a canonical OHLCV CSV file.

    Stored next to the CSV as <name>.meta.json so the same loader works for
    backtest history and live-collected candles.
    """

    schema: str = MARKETDATA_SCHEMA
    symbol: str = "SOL/USD"
    instrument: str = "SOL-PERP"
    venue: str = "jupiter-perps"
    interval_minutes: int = 30
    source: str = "kraken-spot"
    first_ts: str = ""
    last_ts: str = ""
    count: int = 0
    generated_at: str = ""
    notes: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "DatasetMeta":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in payload.items() if k in known}
        return cls(**clean)


def meta_path_for(csv_path: Path) -> Path:
    return csv_path.with_name(csv_path.stem + ".meta.json")


def write_dataset_meta(csv_path: Path, meta: DatasetMeta) -> Path:
    target = meta_path_for(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(meta.to_json_dict(), indent=2), encoding="utf-8")
    return target


def load_dataset_meta(csv_path: Path) -> DatasetMeta | None:
    target = meta_path_for(csv_path)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataError(f"Invalid meta sidecar at {target}: {exc}") from exc
    meta = DatasetMeta.from_json_dict(payload)
    if meta.schema != MARKETDATA_SCHEMA:
        raise DataError(
            f"Unsupported schema '{meta.schema}' in {target}, expected '{MARKETDATA_SCHEMA}'"
        )
    return meta


def write_dataset(
    csv_path: Path,
    candles: list[Candle],
    *,
    symbol: str = "SOL/USD",
    instrument: str = "SOL-PERP",
    venue: str = "jupiter-perps",
    interval_minutes: int = 30,
    source: str = "kraken-spot",
    notes: str = "",
    extras: dict[str, Any] | None = None,
) -> DatasetMeta:
    """Write candles to canonical CSV + sidecar meta.

    The same writer is used by historical fetchers and the live collector so
    backtests and the live trading loop consume an identical schema.
    """
    write_candles(csv_path, candles)
    sorted_candles = sorted(candles, key=lambda c: c.timestamp)
    quality_extras = dict(extras or {})
    if sorted_candles:
        interval_seconds = interval_minutes * 60
        first_epoch = int(sorted_candles[0].timestamp.timestamp())
        last_epoch = int(sorted_candles[-1].timestamp.timestamp())
        expected_count = ((last_epoch - first_epoch) // interval_seconds) + 1
        quality_extras.setdefault("expected_count", expected_count)
        quality_extras.setdefault("missing_count", max(0, expected_count - len(sorted_candles)))
    meta = DatasetMeta(
        schema=MARKETDATA_SCHEMA,
        symbol=symbol,
        instrument=instrument,
        venue=venue,
        interval_minutes=interval_minutes,
        source=source,
        first_ts=sorted_candles[0].timestamp.isoformat() if sorted_candles else "",
        last_ts=sorted_candles[-1].timestamp.isoformat() if sorted_candles else "",
        count=len(sorted_candles),
        generated_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
        extras=quality_extras,
    )
    write_dataset_meta(csv_path, meta)
    return meta


class JupiterPriceClient:
    def __init__(self, api_key: str = "", base_url: str = "") -> None:
        self.api_key = api_key
        if base_url:
            self.base_urls = [base_url.rstrip("/")]
        elif api_key:
            self.base_urls = ["https://api.jup.ag"]
        else:
            self.base_urls = ["https://api.jup.ag", "https://lite-api.jup.ag"]

    def get_price_usd(self, mint: str = WRAPPED_SOL_MINT) -> float:
        query = urllib.parse.urlencode({"ids": mint})
        payload = self._get_json(f"/price/v3?{query}")
        price = self._extract_price(payload, mint)
        if price <= 0:
            raise DataError(f"Jupiter returned a non-positive price for {mint}: {price}")
        return price

    def _get_json(self, path: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for base_url in self.base_urls:
            request = urllib.request.Request(f"{base_url}{path}")
            if self.api_key:
                request.add_header("x-api-key", self.api_key)
            request.add_header("accept", "application/json")
            request.add_header("user-agent", "jupiter-sol-perps-slow-trader/0.1")
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read().decode("utf-8")
                break
            except (urllib.error.HTTPError, OSError) as exc:
                last_error = exc
        else:
            raise DataError(f"Unable to fetch Jupiter price: {last_error}") from last_error
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise DataError(f"Jupiter returned invalid JSON: {body[:200]}") from exc

    @staticmethod
    def _extract_price(payload: dict[str, Any], mint: str) -> float:
        candidates = [payload.get(mint)]
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.append(data.get(mint))
        for candidate in candidates:
            if isinstance(candidate, dict):
                for field_name in ("usdPrice", "price", "priceUsd"):
                    if field_name in candidate:
                        return float(candidate[field_name])
            if isinstance(candidate, (int, float, str)):
                return float(candidate)
        raise DataError(f"Could not find price for {mint} in Jupiter response: {payload}")


def load_candles(path: Path) -> list[Candle]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        candles = [Candle.from_mapping(row) for row in rows]
    return sorted(candles, key=lambda candle: candle.timestamp)


def write_candles(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDLE_FIELDS)
        writer.writeheader()
        for candle in sorted(candles, key=lambda item: item.timestamp):
            writer.writerow(candle.to_csv_row())


def bucket_timestamp(timestamp: datetime, minutes: int) -> datetime:
    utc_timestamp = timestamp.astimezone(timezone.utc)
    bucket_seconds = minutes * 60
    bucket_epoch = int(utc_timestamp.timestamp()) // bucket_seconds * bucket_seconds
    return datetime.fromtimestamp(bucket_epoch, timezone.utc)


def update_candle_with_price(path: Path, price: float, minutes: int, timestamp: datetime | None = None) -> Candle:
    current_time = timestamp or datetime.now(timezone.utc)
    bucket = bucket_timestamp(current_time, minutes)
    candles = load_candles(path)
    if candles and candles[-1].timestamp == bucket:
        previous = candles[-1]
        updated = Candle(
            timestamp=previous.timestamp,
            open=previous.open,
            high=max(previous.high, price),
            low=min(previous.low, price),
            close=price,
            volume=previous.volume,
        )
        candles[-1] = updated
    else:
        updated = Candle(timestamp=bucket, open=price, high=price, low=price, close=price, volume=0.0)
        candles.append(updated)
    write_candles(path, candles)
    return updated


def fetch_binance_spot_candles(symbol: str = "SOLUSDT", interval: str = "30m", limit: int = 500) -> list[Candle]:
    query = urllib.parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": limit})
    url = f"https://api.binance.com/api/v3/klines?{query}"
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_rows = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DataError(f"Unable to fetch Binance candles: {exc}") from exc
    candles: list[Candle] = []
    for raw_row in raw_rows:
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(raw_row[0] / 1000, timezone.utc),
                open=float(raw_row[1]),
                high=float(raw_row[2]),
                low=float(raw_row[3]),
                close=float(raw_row[4]),
                volume=float(raw_row[5]),
            )
        )
    return candles


COINBASE_GRANULARITIES = (60, 300, 900, 3600, 21600, 86400)


def fetch_coinbase_spot_price(product_id: str = "SOL-USD") -> float:
    url = f"https://api.exchange.coinbase.com/products/{product_id.upper()}/ticker"
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "europa-marketdata/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise DataError(f"Unable to fetch Coinbase ticker: HTTP {exc.code} {detail}") from exc
    except OSError as exc:
        raise DataError(f"Unable to fetch Coinbase ticker: {exc}") from exc
    price = float(payload.get("price") or 0.0)
    if price <= 0:
        raise DataError(f"Coinbase returned a non-positive price for {product_id}: {payload}")
    return price


def _coinbase_base_granularity(interval_minutes: int) -> int:
    requested_seconds = interval_minutes * 60
    candidates = [granularity for granularity in COINBASE_GRANULARITIES if requested_seconds % granularity == 0]
    if not candidates:
        raise DataError(f"Coinbase cannot cleanly aggregate to {interval_minutes}m candles")
    return max(candidate for candidate in candidates if candidate <= requested_seconds)


def _fetch_coinbase_chunk(product_id: str, granularity_seconds: int, start_unix: int, end_unix: int) -> list[Candle]:
    start = datetime.fromtimestamp(start_unix, timezone.utc).isoformat().replace("+00:00", "Z")
    end = datetime.fromtimestamp(end_unix, timezone.utc).isoformat().replace("+00:00", "Z")
    query = urllib.parse.urlencode({"granularity": granularity_seconds, "start": start, "end": end})
    url = f"https://api.exchange.coinbase.com/products/{product_id.upper()}/candles?{query}"
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "europa-marketdata/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_rows = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise DataError(f"Unable to fetch Coinbase candles: HTTP {exc.code} {detail}") from exc
    except OSError as exc:
        raise DataError(f"Unable to fetch Coinbase candles: {exc}") from exc
    candles: list[Candle] = []
    for raw_row in raw_rows:
        # Coinbase rows are [time, low, high, open, close, volume].
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(raw_row[0]), timezone.utc),
                open=float(raw_row[3]),
                high=float(raw_row[2]),
                low=float(raw_row[1]),
                close=float(raw_row[4]),
                volume=float(raw_row[5]),
            )
        )
    return sorted(candles, key=lambda candle: candle.timestamp)


def aggregate_candles(candles: list[Candle], interval_minutes: int) -> list[Candle]:
    buckets: dict[datetime, list[Candle]] = {}
    for candle in sorted(candles, key=lambda item: item.timestamp):
        buckets.setdefault(bucket_timestamp(candle.timestamp, interval_minutes), []).append(candle)
    aggregated: list[Candle] = []
    for timestamp, bucket in sorted(buckets.items()):
        aggregated.append(
            Candle(
                timestamp=timestamp,
                open=bucket[0].open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket),
                close=bucket[-1].close,
                volume=sum(item.volume for item in bucket),
            )
        )
    return aggregated


def fetch_coinbase_history_paginated(
    product_id: str = "SOL-USD",
    interval_minutes: int = 30,
    days: int = 200,
    *,
    sleep_seconds: float = 0.25,
    max_pages: int = 300,
) -> list[Candle]:
    base_granularity = _coinbase_base_granularity(interval_minutes)
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - days * 86400
    max_span = base_granularity * 299
    cursor = start_ts
    pages = 0
    seen: dict[datetime, Candle] = {}
    while cursor < end_ts and pages < max_pages:
        chunk_end = min(cursor + max_span, end_ts)
        chunk = _fetch_coinbase_chunk(product_id, base_granularity, cursor, chunk_end)
        pages += 1
        for candle in chunk:
            seen[candle.timestamp] = candle
        cursor = chunk_end
        time.sleep(sleep_seconds)
    if cursor < end_ts:
        raise DataError(f"Coinbase pagination stopped before end of requested window after {pages} pages")
    cutoff = datetime.fromtimestamp(start_ts, timezone.utc)
    raw_candles = sorted([candle for candle in seen.values() if candle.timestamp >= cutoff], key=lambda candle: candle.timestamp)
    return aggregate_candles(raw_candles, interval_minutes)


def fetch_kraken_spot_candles(pair: str = "SOLUSD", interval_minutes: int = 30, limit: int = 500) -> list[Candle]:
    query = urllib.parse.urlencode({"pair": pair.upper(), "interval": interval_minutes})
    url = f"https://api.kraken.com/0/public/OHLC?{query}"
    request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "jupiter-sol-perps-slow-trader/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DataError(f"Unable to fetch Kraken candles: {exc}") from exc
    errors = payload.get("error") or []
    if errors:
        raise DataError(f"Kraken returned errors: {errors}")
    result = payload.get("result") or {}
    candle_rows = []
    for key, value in result.items():
        if key != "last":
            candle_rows = value
            break
    candles: list[Candle] = []
    for raw_row in candle_rows[-limit:]:
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(float(raw_row[0]), timezone.utc),
                open=float(raw_row[1]),
                high=float(raw_row[2]),
                low=float(raw_row[3]),
                close=float(raw_row[4]),
                volume=float(raw_row[6]),
            )
        )
    return candles


def parse_interval_minutes(interval: str) -> int:
    value = interval.strip().lower()
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("h"):
        return int(value[:-1]) * 60
    if value.endswith("d"):
        return int(value[:-1]) * 60 * 24
    return int(value)


def _fetch_kraken_chunk(pair: str, interval_minutes: int, since: int | None) -> tuple[list[Candle], int]:
    params: dict[str, Any] = {"pair": pair.upper(), "interval": interval_minutes}
    if since is not None:
        params["since"] = since
    query = urllib.parse.urlencode(params)
    url = f"https://api.kraken.com/0/public/OHLC?{query}"
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "europa-marketdata/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DataError(f"Unable to fetch Kraken candles: {exc}") from exc
    errors = payload.get("error") or []
    if errors:
        raise DataError(f"Kraken returned errors: {errors}")
    result = payload.get("result") or {}
    last = int(result.get("last", 0) or 0)
    candle_rows: list[Any] = []
    for key, value in result.items():
        if key != "last":
            candle_rows = value
            break
    candles: list[Candle] = []
    for raw_row in candle_rows:
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(float(raw_row[0]), timezone.utc),
                open=float(raw_row[1]),
                high=float(raw_row[2]),
                low=float(raw_row[3]),
                close=float(raw_row[4]),
                volume=float(raw_row[6]),
            )
        )
    return candles, last


def fetch_kraken_history_paginated(
    pair: str = "SOLUSD",
    interval_minutes: int = 30,
    days: int = 200,
    *,
    sleep_seconds: float = 1.2,
    max_pages: int = 200,
) -> list[Candle]:
    """Pull `days` of Kraken OHLC by paging through `since`.

    NOTE: Kraken's public OHLC endpoint only retains roughly the most recent
    720 bars regardless of `since`, so this realistically returns at most
    ~15 days at 30m / 30 days at 1h / 720 days at 1d. For Jupiter Perps
    backtests, prefer Pyth Benchmarks with the exact feed symbol/id from
    `config/markets.json`; Coinbase is a fallback research proxy.
    """
    end_ts = datetime.now(timezone.utc).timestamp()
    start_ts = int(end_ts - days * 86400)
    since: int | None = start_ts
    seen: dict[datetime, Candle] = {}
    pages = 0
    while pages < max_pages:
        chunk, last = _fetch_kraken_chunk(pair, interval_minutes, since)
        pages += 1
        if not chunk:
            break
        progressed = False
        for candle in chunk:
            if candle.timestamp not in seen:
                seen[candle.timestamp] = candle
                progressed = True
        new_since = last if last else int(chunk[-1].timestamp.timestamp())
        if since is not None and new_since <= since:
            break
        since = new_since
        if not progressed:
            break
        if since >= end_ts:
            break
        time.sleep(sleep_seconds)
    cutoff = datetime.fromtimestamp(start_ts, timezone.utc)
    return sorted([c for c in seen.values() if c.timestamp >= cutoff], key=lambda c: c.timestamp)


# ----- Pyth oracle / benchmarks ------------------------------------------

PYTH_BENCHMARKS_BASE = "https://benchmarks.pyth.network"
PYTH_HERMES_BASE = "https://hermes.pyth.network"


def _normalize_pyth_price(price_payload: dict[str, Any]) -> float:
    price = float(price_payload["price"])
    expo = int(price_payload["expo"])
    return price * (10 ** expo)


def fetch_pyth_spot_price(price_id: str) -> float:
    clean_id = price_id.removeprefix("0x")
    if not clean_id:
        raise DataError("Pyth price_id is required")
    query = urllib.parse.urlencode({"ids[]": clean_id})
    url = f"{PYTH_HERMES_BASE}/v2/updates/price/latest?{query}"
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "europa-marketdata/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise DataError(f"Unable to fetch Pyth price: HTTP {exc.code} {detail}") from exc
    except OSError as exc:
        raise DataError(f"Unable to fetch Pyth price: {exc}") from exc
    parsed = payload.get("parsed") or []
    if not parsed:
        raise DataError(f"Pyth returned no parsed price for {clean_id}: {payload}")
    price = _normalize_pyth_price(parsed[0]["price"])
    if price <= 0:
        raise DataError(f"Pyth returned a non-positive price for {clean_id}: {payload}")
    return price


def _fetch_pyth_chunk(
    symbol: str,
    resolution: str,
    from_unix: int,
    to_unix: int,
) -> list[Candle]:
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "from": from_unix,
        "to": to_unix,
    }
    query = urllib.parse.urlencode(params)
    url = f"{PYTH_BENCHMARKS_BASE}/v1/shims/tradingview/history?{query}"
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "europa-marketdata/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError as exc:
        raise DataError(f"Unable to fetch Pyth benchmarks: {exc}") from exc
    status = payload.get("s")
    if status == "no_data":
        return []
    if status != "ok":
        raise DataError(f"Pyth benchmarks returned status={status}: {payload}")
    times: list[int] = payload.get("t") or []
    opens: list[float] = payload.get("o") or []
    highs: list[float] = payload.get("h") or []
    lows: list[float] = payload.get("l") or []
    closes: list[float] = payload.get("c") or []
    volumes: list[float] = payload.get("v") or [0.0] * len(times)
    candles: list[Candle] = []
    for index, ts in enumerate(times):
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(ts), timezone.utc),
                open=float(opens[index]),
                high=float(highs[index]),
                low=float(lows[index]),
                close=float(closes[index]),
                volume=float(volumes[index]) if index < len(volumes) else 0.0,
            )
        )
    return candles


def _pyth_resolution(interval_minutes: int) -> str:
    # Pyth's TradingView shim uses minutes for sub-day, "D" for daily, "W" weekly.
    if interval_minutes % (60 * 24) == 0:
        days = interval_minutes // (60 * 24)
        return "D" if days == 1 else f"{days}D"
    if interval_minutes % 60 == 0:
        return str(interval_minutes)  # shim accepts minute count for hourly too
    return str(interval_minutes)


def fetch_pyth_history_paginated(
    symbol: str = "Crypto.SOL/USD",
    interval_minutes: int = 30,
    days: int = 200,
    *,
    chunk_days: int = 30,
    sleep_seconds: float = 0.4,
    max_pages: int = 200,
) -> list[Candle]:
    """Pull `days` of Pyth oracle OHLCV via the TradingView shim.

    Pyth Benchmarks are the preferred history source for Jupiter Perps because
    they align with the oracle family used by Jupiter's perps markets. Keep the
    configured symbol and feed id together so a bad symbol lookup is easy to
    detect against Hermes latest prices.
    """
    resolution = _pyth_resolution(interval_minutes)
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - days * 86400
    seen: dict[datetime, Candle] = {}
    cursor = start_ts
    step = chunk_days * 86400
    pages = 0
    while cursor < end_ts and pages < max_pages:
        chunk_end = min(cursor + step, end_ts)
        chunk = _fetch_pyth_chunk(symbol, resolution, cursor, chunk_end)
        pages += 1
        for candle in chunk:
            seen[candle.timestamp] = candle
        cursor = chunk_end + 1
        time.sleep(sleep_seconds)
    cutoff = datetime.fromtimestamp(start_ts, timezone.utc)
    return sorted([c for c in seen.values() if c.timestamp >= cutoff], key=lambda c: c.timestamp)


def update_canonical_with_price(
    csv_path: Path,
    price: float,
    *,
    interval_minutes: int,
    symbol: str = "SOL/USD",
    instrument: str = "SOL-PERP",
    venue: str = "jupiter-perps",
    source: str = "jupiter-price-v3",
    timestamp: datetime | None = None,
) -> Candle:
    """Live-tick updater that keeps the canonical CSV + meta sidecar in sync.

    Same on-disk format as `write_dataset`, so backtest and live consume the
    exact same schema.
    """
    candle = update_candle_with_price(csv_path, price, interval_minutes, timestamp=timestamp)
    candles = load_candles(csv_path)
    write_dataset(
        csv_path,
        candles,
        symbol=symbol,
        instrument=instrument,
        venue=venue,
        interval_minutes=interval_minutes,
        source=source,
        notes="live-collected",
    )
    return candle


def collect_forever(client: JupiterPriceClient, path: Path, minutes: int, sleep_seconds: int = 60) -> None:
    while True:
        price = client.get_price_usd()
        update_canonical_with_price(path, price, interval_minutes=minutes)
        time.sleep(sleep_seconds)
