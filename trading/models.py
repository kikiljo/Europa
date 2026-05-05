from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalAction(str, Enum):
    HOLD = "hold"
    OPEN = "open"
    CLOSE = "close"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @staticmethod
    def parse_timestamp(raw_value: str) -> datetime:
        value = raw_value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "Candle":
        raw_ts = row.get("ts") if "ts" in row else row.get("timestamp")
        if raw_ts is None:
            raise ValueError(f"candle row missing 'ts'/'timestamp': {row}")
        return cls(
            timestamp=cls.parse_timestamp(str(raw_ts)),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0) or 0),
        )

    def to_csv_row(self) -> dict[str, str]:
        return {
            "ts": self.timestamp.astimezone(timezone.utc).isoformat(),
            "open": f"{self.open:.10f}",
            "high": f"{self.high:.10f}",
            "low": f"{self.low:.10f}",
            "close": f"{self.close:.10f}",
            "volume": f"{self.volume:.10f}",
        }


@dataclass
class Position:
    side: Side
    entry_price: float
    size_usd: float
    collateral_usd: float
    leverage: float
    opened_at: datetime
    stop_loss: float
    take_profit: float
    position_id: str = ""

    def unrealized_pnl_usd(self, mark_price: float) -> float:
        if self.side == Side.LONG:
            return (mark_price - self.entry_price) / self.entry_price * self.size_usd
        return (self.entry_price - mark_price) / self.entry_price * self.size_usd

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side"] = self.side.value
        payload["opened_at"] = self.opened_at.astimezone(timezone.utc).isoformat()
        return payload

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "Position":
        return cls(
            side=Side(payload["side"]),
            entry_price=float(payload["entry_price"]),
            size_usd=float(payload["size_usd"]),
            collateral_usd=float(payload["collateral_usd"]),
            leverage=float(payload["leverage"]),
            opened_at=Candle.parse_timestamp(str(payload["opened_at"])),
            stop_loss=float(payload["stop_loss"]),
            take_profit=float(payload["take_profit"]),
            position_id=str(payload.get("position_id", "")),
        )


@dataclass(frozen=True)
class Signal:
    action: SignalAction
    reason: str
    side: Side | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class OrderIntent:
    action: SignalAction
    asset: str
    side: Side | None
    size_usd: float
    collateral_usd: float
    leverage: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    reason: str
    position_id: str = ""


@dataclass(frozen=True)
class ExecutionReport:
    accepted: bool
    dry_run: bool
    message: str
    raw_response: dict[str, Any] | None = None
    signature: str = ""
    position_id: str = ""


@dataclass(frozen=True)
class BacktestTrade:
    opened_at: datetime
    closed_at: datetime
    side: Side
    entry_price: float
    exit_price: float
    size_usd: float
    pnl_usd: float
    fees_usd: float
    reason: str
