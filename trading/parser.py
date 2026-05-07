from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from trading.domain import Candle


@dataclass(frozen=True)
class MarketEvent:
    market: str
    timestamp: datetime
    price: float
    source: str
    raw: dict[str, Any]


class RealtimeMarketParser(Protocol):
    def parse(self, payload: dict[str, Any]) -> MarketEvent:
        raise NotImplementedError


class PricePayloadParser:
    def __init__(self, market: str, source: str) -> None:
        self.market = market
        self.source = source

    def parse(self, payload: dict[str, Any]) -> MarketEvent:
        price = float(payload["price"])
        raw_timestamp = payload.get("timestamp") or payload.get("ts")
        if raw_timestamp is None:
            timestamp = datetime.now(timezone.utc)
        else:
            timestamp = Candle.parse_timestamp(str(raw_timestamp))
        return MarketEvent(
            market=self.market,
            timestamp=timestamp,
            price=price,
            source=self.source,
            raw=payload,
        )


def event_to_candle(event: MarketEvent) -> Candle:
    return Candle(
        timestamp=event.timestamp,
        open=event.price,
        high=event.price,
        low=event.price,
        close=event.price,
        volume=0.0,
    )