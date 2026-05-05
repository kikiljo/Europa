from __future__ import annotations

from datetime import datetime, timezone

from trading.config import RiskConfig, StrategyConfig
from trading.models import OrderIntent, Position, Side, Signal, SignalAction


class RiskError(RuntimeError):
    pass


class RiskManager:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig) -> None:
        self.strategy_config = strategy_config
        self.risk_config = risk_config

    def order_from_signal(
        self,
        signal: Signal,
        current_time: datetime,
        weekly_trade_count: int,
        daily_realized_pnl_usd: float = 0.0,
        open_position: Position | None = None,
    ) -> OrderIntent | None:
        if signal.action == SignalAction.HOLD:
            return None
        if signal.action == SignalAction.CLOSE:
            if open_position is None:
                raise RiskError("close signal received without an open position")
            return OrderIntent(
                action=SignalAction.CLOSE,
                asset=self.strategy_config.asset,
                side=open_position.side,
                size_usd=open_position.size_usd,
                collateral_usd=open_position.collateral_usd,
                leverage=open_position.leverage,
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reason=signal.reason,
                position_id=open_position.position_id,
            )
        return self._open_order(signal, current_time, weekly_trade_count, daily_realized_pnl_usd)

    def _open_order(
        self,
        signal: Signal,
        current_time: datetime,
        weekly_trade_count: int,
        daily_realized_pnl_usd: float,
    ) -> OrderIntent:
        if signal.side is None or signal.entry_price is None or signal.stop_loss is None or signal.take_profit is None:
            raise RiskError("open signal is missing side, entry, stop, or take profit")
        if weekly_trade_count >= self.risk_config.max_weekly_trades:
            raise RiskError("weekly trade cap reached")
        daily_loss_limit = -self.risk_config.equity_usd * self.risk_config.max_daily_loss_pct
        if daily_realized_pnl_usd <= daily_loss_limit:
            raise RiskError("daily realized loss limit reached")
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance <= 0:
            raise RiskError("stop distance must be positive")
        stop_pct = stop_distance / signal.entry_price
        risk_usd = self.risk_config.equity_usd * self.risk_config.risk_per_trade_pct
        raw_size_usd = risk_usd / stop_pct
        max_size_usd = self.risk_config.equity_usd * self.risk_config.max_position_equity_pct * self.risk_config.max_leverage
        size_usd = min(raw_size_usd, max_size_usd)
        leverage = min(self.risk_config.default_leverage, self.risk_config.max_leverage)
        collateral_usd = size_usd / leverage
        if size_usd < self.risk_config.min_order_usd:
            raise RiskError(f"calculated order size {size_usd:.2f} is below minimum {self.risk_config.min_order_usd:.2f}")

        return OrderIntent(
            action=SignalAction.OPEN,
            asset=self.strategy_config.asset,
            side=signal.side,
            size_usd=size_usd,
            collateral_usd=collateral_usd,
            leverage=leverage,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )


def iso_week_key(timestamp: datetime) -> tuple[int, int]:
    calendar = timestamp.astimezone(timezone.utc).isocalendar()
    return calendar.year, calendar.week
