from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading.config import WRAPPED_SOL_MINT
from trading.models import Candle


CANDLE_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]


class DataError(RuntimeError):
    pass


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
    bucket_minute = utc_timestamp.minute - utc_timestamp.minute % minutes
    return utc_timestamp.replace(minute=bucket_minute, second=0, microsecond=0)


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
    return int(value)


def collect_forever(client: JupiterPriceClient, path: Path, minutes: int, sleep_seconds: int = 60) -> None:
    while True:
        price = client.get_price_usd()
        update_candle_with_price(path=path, price=price, minutes=minutes)
        time.sleep(sleep_seconds)
