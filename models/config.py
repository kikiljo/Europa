from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelShapeConfig:
    name: str = "baseline_factor_ensemble"
    label: str = "Baseline Factor Ensemble"
    input_signal_names: tuple[str, ...] = ("fast_ema_slope", "slow_ema_slope", "ema_spread", "rsi_momentum", "rsi_reversion")
    output_signal_name: str = "baseline_model_score"
    output_signal_label: str = "Baseline Model Score"
    target_horizon_ticks: int = 4
    normalization: str = "expanding_zscore_30"
    trend_weight: float = 0.45
    rsi_weight: float = 0.30
    breakout_weight: float = 0.25


@dataclass(frozen=True)
class TrainingConfig:
    shape: ModelShapeConfig = field(default_factory=ModelShapeConfig)
    train_fraction: float = 0.70
    min_samples: int = 200
    target_return_name: str = "forward_return"

    def validate(self) -> None:
        if not 0 < self.train_fraction < 1:
            raise ValueError("train_fraction must be between 0 and 1")
        if self.min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if self.shape.target_horizon_ticks <= 0:
            raise ValueError("target_horizon_ticks must be positive")