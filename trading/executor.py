from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from trading.algo import TradingAlgorithm, TradingDecision
from trading.broker import DryRunBroker, JupiterCliPerpsBroker
from trading.config import AppConfig, ExecutionConfig
from trading.domain import Candle, ExecutionReport, OrderIntent, Position, SignalAction
from trading.gateway import BrokerGateway, TradingGateway
from trading.inference import InferenceEngine, InferenceResult, StrategyInferenceEngine
from trading.storage import append_trade_log, count_weekly_open_trades, daily_realized_pnl, load_position, save_position


@dataclass(frozen=True)
class ExecutorRunResult:
    inference: InferenceResult
    decision: TradingDecision
    report: ExecutionReport | None


class LiveTradingExecutor:
    def __init__(
        self,
        config: AppConfig,
        execution_config: ExecutionConfig,
        inference: InferenceEngine,
        algorithm: TradingAlgorithm,
        gateway: TradingGateway,
    ) -> None:
        self.config = config
        self.execution_config = execution_config
        self.inference = inference
        self.algorithm = algorithm
        self.gateway = gateway

    @classmethod
    def from_config(cls, config: AppConfig, execution_config: ExecutionConfig) -> "LiveTradingExecutor":
        broker = DryRunBroker() if execution_config.dry_run else JupiterCliPerpsBroker(execution_config)
        return cls(
            config=config,
            execution_config=execution_config,
            inference=StrategyInferenceEngine(config.strategy, config.risk),
            algorithm=TradingAlgorithm(config.strategy, config.risk),
            gateway=BrokerGateway(broker),
        )

    def run_once(self, candles: list[Candle]) -> ExecutorRunResult:
        if not candles:
            raise ValueError("cannot run executor without candles")
        now = datetime.now(timezone.utc)
        open_position = load_position(self.execution_config.state_path)
        weekly_count = count_weekly_open_trades(self.execution_config.trade_log_path, now)
        daily_pnl = daily_realized_pnl(self.execution_config.trade_log_path, now)
        inference = self.inference.infer(candles, open_position, weekly_count)
        decision = self.algorithm.decide(inference.signal, candles[-1].timestamp, weekly_count, daily_pnl, open_position)
        if decision.order is None:
            return ExecutorRunResult(inference=inference, decision=decision, report=None)
        report = self.gateway.execute(decision.order)
        realized_pnl = self._realized_pnl(decision.order, open_position, candles[-1])
        append_trade_log(self.execution_config.trade_log_path, decision.order, report, realized_pnl)
        self._update_state_after_execution(decision.order, report, candles[-1].timestamp)
        return ExecutorRunResult(inference=inference, decision=decision, report=report)

    def positions(self) -> dict:
        return self.gateway.positions()

    def _update_state_after_execution(self, order: OrderIntent, report: ExecutionReport, opened_at: datetime) -> None:
        if not report.accepted:
            return
        if order.action == SignalAction.OPEN:
            if order.side is None:
                return
            position = Position(
                side=order.side,
                entry_price=order.entry_price or 0.0,
                size_usd=order.size_usd,
                collateral_usd=order.collateral_usd,
                leverage=order.leverage,
                opened_at=opened_at,
                stop_loss=order.stop_loss or 0.0,
                take_profit=order.take_profit or 0.0,
                position_id=report.position_id,
            )
            save_position(self.execution_config.state_path, position)
        elif order.action == SignalAction.CLOSE:
            save_position(self.execution_config.state_path, None)

    @staticmethod
    def _realized_pnl(order: OrderIntent, open_position: Position | None, candle: Candle) -> float:
        if order.action == SignalAction.CLOSE and open_position is not None:
            return open_position.unrealized_pnl_usd(candle.close)
        return 0.0