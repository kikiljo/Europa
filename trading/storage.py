from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading.domain import ExecutionReport, OrderIntent, Position, SignalAction
from trading.risk import iso_week_key


TRADE_LOG_FIELDS = [
    "timestamp",
    "action",
    "asset",
    "side",
    "size_usd",
    "collateral_usd",
    "leverage",
    "entry_price",
    "stop_loss",
    "take_profit",
    "reason",
    "accepted",
    "dry_run",
    "signature",
    "position_id",
    "message",
    "realized_pnl_usd",
]


def append_trade_log(path: Path, order: OrderIntent, report: ExecutionReport, realized_pnl_usd: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": order.action.value,
                "asset": order.asset,
                "side": order.side.value if order.side else "",
                "size_usd": f"{order.size_usd:.6f}",
                "collateral_usd": f"{order.collateral_usd:.6f}",
                "leverage": f"{order.leverage:.4f}",
                "entry_price": _optional_float(order.entry_price),
                "stop_loss": _optional_float(order.stop_loss),
                "take_profit": _optional_float(order.take_profit),
                "reason": order.reason,
                "accepted": str(report.accepted),
                "dry_run": str(report.dry_run),
                "signature": report.signature,
                "position_id": report.position_id,
                "message": report.message,
                "realized_pnl_usd": f"{realized_pnl_usd:.6f}",
            }
        )


def count_weekly_open_trades(path: Path, now: datetime) -> int:
    if not path.exists():
        return 0
    current_week = iso_week_key(now)
    count = 0
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("action") != SignalAction.OPEN.value or row.get("accepted") != "True":
                continue
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if iso_week_key(timestamp) == current_week:
                count += 1
    return count


def daily_realized_pnl(path: Path, now: datetime) -> float:
    if not path.exists():
        return 0.0
    current_day = now.astimezone(timezone.utc).date()
    total = 0.0
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.astimezone(timezone.utc).date() == current_day:
                total += float(row.get("realized_pnl_usd") or 0)
    return total


def load_position(path: Path) -> Position | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    position_payload = payload.get("open_position")
    if not position_payload:
        return None
    return Position.from_json_dict(position_payload)


def save_position(path: Path, position: Position | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"open_position": position.to_json_dict() if position else None}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10f}"
