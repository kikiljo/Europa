from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from factors import compute_factor_series
from models import default_model_signal_model
from trading.config import RiskConfig, StrategyConfig
from trading.domain import Candle, Position, Signal
from trading.signals import ResearchSignal
from trading.strategy import SwingPerpsStrategy


@dataclass(frozen=True)
class InferenceResult:
    signal: Signal
    model_signals: list[ResearchSignal]
    factor_ready: bool


class InferenceEngine(Protocol):
    def infer(self, candles: list[Candle], open_position: Position | None, weekly_trade_count: int) -> InferenceResult:
        raise NotImplementedError


class StrategyInferenceEngine:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig) -> None:
        self.strategy_config = strategy_config
        self.strategy = SwingPerpsStrategy(strategy_config, risk_config)
        self.model = default_model_signal_model()

    def infer(self, candles: list[Candle], open_position: Position | None, weekly_trade_count: int) -> InferenceResult:
        signal = self.strategy.analyze(candles, open_position, weekly_trade_count)
        if not candles:
            return InferenceResult(signal=signal, model_signals=[], factor_ready=False)
        factor_series = compute_factor_series(candles, self.strategy_config)
        latest_factors = factor_series.latest()
        model_output = self.model.predict(candles, factor_series) if latest_factors.is_ready() else None
        return InferenceResult(
            signal=signal,
            model_signals=model_output.signals if model_output else [],
            factor_ready=latest_factors.is_ready(),
        )