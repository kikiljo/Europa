from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from factors import FactorSeries
from factors.signals import build_factor_signals
from models.config import TrainingConfig
from trading.domain import Candle
from trading.signals import future_returns


@dataclass(frozen=True)
class TrainingDataset:
    timestamps: list[datetime]
    feature_names: list[str]
    rows: list[list[float]]
    target_returns: list[float]
    target_horizon_ticks: int


@dataclass(frozen=True)
class TrainingResult:
    model_name: str
    sample_count: int
    train_count: int
    validation_count: int
    feature_names: list[str]
    target_horizon_ticks: int
    train_mean_return: float
    validation_mean_return: float
    notes: str


def build_training_dataset(candles: list[Candle], factors: FactorSeries, config: TrainingConfig | None = None) -> TrainingDataset:
    training_config = config or TrainingConfig()
    training_config.validate()
    factor_signals = build_factor_signals(factors, names=list(training_config.shape.input_signal_names))
    returns = future_returns(candles, [training_config.shape.target_horizon_ticks])[training_config.shape.target_horizon_ticks]
    feature_names = [signal.name for signal in factor_signals]
    timestamps: list[datetime] = []
    rows: list[list[float]] = []
    target_returns: list[float] = []
    for index, candle in enumerate(candles):
        feature_row: list[float] = []
        row_ready = True
        for signal in factor_signals:
            value = signal.values[index]
            if value is None:
                row_ready = False
                break
            feature_row.append(value)
        target = returns[index]
        if not row_ready or target is None:
            continue
        timestamps.append(candle.timestamp)
        rows.append(feature_row)
        target_returns.append(target)
    return TrainingDataset(
        timestamps=timestamps,
        feature_names=feature_names,
        rows=rows,
        target_returns=target_returns,
        target_horizon_ticks=training_config.shape.target_horizon_ticks,
    )


def train_baseline_model(candles: list[Candle], factors: FactorSeries, config: TrainingConfig | None = None) -> TrainingResult:
    training_config = config or TrainingConfig()
    dataset = build_training_dataset(candles, factors, training_config)
    if len(dataset.rows) < training_config.min_samples:
        raise ValueError(f"need at least {training_config.min_samples} samples, got {len(dataset.rows)}")
    split_index = int(len(dataset.rows) * training_config.train_fraction)
    train_returns = dataset.target_returns[:split_index]
    validation_returns = dataset.target_returns[split_index:]
    return TrainingResult(
        model_name=training_config.shape.name,
        sample_count=len(dataset.rows),
        train_count=len(train_returns),
        validation_count=len(validation_returns),
        feature_names=dataset.feature_names,
        target_horizon_ticks=dataset.target_horizon_ticks,
        train_mean_return=_mean(train_returns),
        validation_mean_return=_mean(validation_returns),
        notes="Baseline scaffold only; no fitted parameters are persisted yet.",
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)