from __future__ import annotations

from dataclasses import dataclass

from factors import FactorSeries
from models.config import ModelShapeConfig
from trading.domain import Candle
from trading.signals import ResearchSignal, expanding_zscore_normalize


@dataclass(frozen=True)
class ModelSignalOutput:
    model_name: str
    shape: ModelShapeConfig
    signals: list[ResearchSignal]


class BaselineSignalModel:
    def __init__(self, shape: ModelShapeConfig | None = None) -> None:
        self.shape = shape or ModelShapeConfig()
        self.name = self.shape.name
        self.label = self.shape.label

    def predict(self, candles: list[Candle], factors: FactorSeries) -> ModelSignalOutput:
        closes = [candle.close for candle in candles]
        trend_raw = _trend_spread(factors, closes)
        rsi_raw = _rsi_centered(factors)
        breakout_raw = _breakout_position(factors)

        trend_signal = expanding_zscore_normalize(trend_raw)
        rsi_signal = rsi_raw
        breakout_signal = expanding_zscore_normalize(breakout_raw)
        score = _weighted_score(
            components=[
                (trend_signal, self.shape.trend_weight),
                (rsi_signal, self.shape.rsi_weight),
                (breakout_signal, self.shape.breakout_weight),
            ]
        )
        normalized_score = expanding_zscore_normalize(score)

        return ModelSignalOutput(
            model_name=self.name,
            shape=self.shape,
            signals=[
                ResearchSignal(
                    name=self.shape.output_signal_name,
                    label=self.shape.output_signal_label,
                    source="model",
                    group="ensemble",
                    raw_values=score,
                    values=normalized_score,
                    description="Weighted directional score from trend spread, RSI, and breakout position.",
                    normalization="expanding_zscore_30",
                )
            ],
        )


def default_model_signal_model() -> BaselineSignalModel:
    return BaselineSignalModel()


def _trend_spread(factors: FactorSeries, closes: list[float]) -> list[float | None]:
    output: list[float | None] = []
    for close, fast, slow in zip(closes, factors.fast_ema, factors.slow_ema):
        if close == 0 or fast is None or slow is None:
            output.append(None)
        else:
            output.append((fast - slow) / close)
    return output


def _rsi_centered(factors: FactorSeries) -> list[float | None]:
    output: list[float | None] = []
    for value in factors.rsi:
        output.append(None if value is None else (value - 50.0) / 50.0)
    return output


def _breakout_position(factors: FactorSeries) -> list[float | None]:
    output: list[float | None] = []
    for close, high, low in zip(factors.closes, factors.breakout_high, factors.breakout_low):
        if high is None or low is None or high <= low:
            output.append(None)
            continue
        midpoint = (high + low) / 2
        half_range = (high - low) / 2
        output.append((close - midpoint) / half_range)
    return output


def _weighted_score(components: list[tuple[list[float | None], float]]) -> list[float | None]:
    if not components:
        return []
    length = len(components[0][0])
    output: list[float | None] = []
    for index in range(length):
        weighted_sum = 0.0
        weight_sum = 0.0
        for values, weight in components:
            value = values[index]
            if value is None:
                continue
            weighted_sum += value * weight
            weight_sum += weight
        output.append(weighted_sum / weight_sum if weight_sum else None)
    return output