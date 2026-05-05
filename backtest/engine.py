from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading.config import RiskConfig, StrategyConfig
from trading.domain import BacktestTrade, Candle, Position, SignalAction
from trading.risk import RiskError, RiskManager, iso_week_key
from trading.strategy import SwingPerpsStrategy


@dataclass(frozen=True)
class BacktestResult:
    trades: list[BacktestTrade]
    final_equity: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float

    def summary(self) -> dict[str, float | int]:
        return {
            "trades": len(self.trades),
            "final_equity": round(self.final_equity, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 2),
        }


class BacktestEngine:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig) -> None:
        self.strategy_config = strategy_config
        self.risk_config = risk_config
        self.strategy = SwingPerpsStrategy(strategy_config, risk_config)
        self.risk_manager = RiskManager(strategy_config, risk_config)

    def run(self, candles: list[Candle]) -> BacktestResult:
        equity = self.risk_config.equity_usd
        peak_equity = equity
        max_drawdown_pct = 0.0
        trades: list[BacktestTrade] = []
        open_position: Position | None = None
        last_trade_index: int | None = None
        weekly_open_counts: dict[tuple[int, int], int] = {}

        for index, candle in enumerate(candles):
            visible_candles = candles[: index + 1]
            weekly_key = iso_week_key(candle.timestamp)
            weekly_trade_count = weekly_open_counts.get(weekly_key, 0)
            signal = self.strategy.analyze(visible_candles, open_position, weekly_trade_count, last_trade_index)
            if signal.action == SignalAction.OPEN and open_position is None:
                try:
                    order = self.risk_manager.order_from_signal(signal, candle.timestamp, weekly_trade_count)
                except RiskError:
                    continue
                if order is None or order.side is None or order.entry_price is None or order.stop_loss is None or order.take_profit is None:
                    continue
                open_position = Position(
                    side=order.side,
                    entry_price=candle.close,
                    size_usd=order.size_usd,
                    collateral_usd=order.collateral_usd,
                    leverage=order.leverage,
                    opened_at=candle.timestamp,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                )
                weekly_open_counts[weekly_key] = weekly_trade_count + 1
                last_trade_index = index
            elif signal.action == SignalAction.CLOSE and open_position is not None:
                trade, net_pnl = self._close_position(open_position, candle, signal.reason)
                trades.append(trade)
                equity += net_pnl
                open_position = None
                last_trade_index = index

            peak_equity = max(peak_equity, equity)
            if peak_equity > 0:
                drawdown_pct = (peak_equity - equity) / peak_equity * 100
                max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        if open_position is not None and candles:
            trade, net_pnl = self._close_position(open_position, candles[-1], "end of backtest")
            trades.append(trade)
            equity += net_pnl

        return BacktestResult(
            trades=trades,
            final_equity=equity,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=self._win_rate(trades),
            profit_factor=self._profit_factor(trades),
        )

    def _close_position(self, position: Position, candle: Candle, reason: str) -> tuple[BacktestTrade, float]:
        gross_pnl = position.unrealized_pnl_usd(candle.close)
        fees = position.size_usd * self.risk_config.fee_bps * 2 / 10000
        net_pnl = gross_pnl - fees
        trade = BacktestTrade(
            opened_at=position.opened_at,
            closed_at=candle.timestamp,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=candle.close,
            size_usd=position.size_usd,
            pnl_usd=net_pnl,
            fees_usd=fees,
            reason=reason,
        )
        return trade, net_pnl

    @staticmethod
    def _win_rate(trades: list[BacktestTrade]) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for trade in trades if trade.pnl_usd > 0)
        return wins / len(trades) * 100

    @staticmethod
    def _profit_factor(trades: list[BacktestTrade]) -> float:
        gross_profit = sum(trade.pnl_usd for trade in trades if trade.pnl_usd > 0)
        gross_loss = abs(sum(trade.pnl_usd for trade in trades if trade.pnl_usd < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
