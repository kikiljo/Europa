from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading.config import RiskConfig, StrategyConfig
from trading.domain import OrderIntent, Position, Signal
from trading.risk import RiskError, RiskManager


@dataclass(frozen=True)
class TradingDecision:
    signal: Signal
    order: OrderIntent | None
    blocked_reason: str = ""


class TradingAlgorithm:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig) -> None:
        self.risk_manager = RiskManager(strategy_config, risk_config)

    def decide(
        self,
        signal: Signal,
        current_time: datetime,
        weekly_trade_count: int,
        daily_realized_pnl_usd: float,
        open_position: Position | None,
    ) -> TradingDecision:
        try:
            order = self.risk_manager.order_from_signal(
                signal,
                current_time,
                weekly_trade_count,
                daily_realized_pnl_usd,
                open_position,
            )
        except RiskError as exc:
            return TradingDecision(signal=signal, order=None, blocked_reason=str(exc))
        return TradingDecision(signal=signal, order=order)