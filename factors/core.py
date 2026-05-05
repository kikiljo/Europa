from __future__ import annotations

from dataclasses import dataclass

from trading.config import StrategyConfig
from trading.domain import Candle
from trading.indicators import average_true_range, exponential_moving_average, relative_strength_index, rolling_high, rolling_low


MaybeFloat = float | None


@dataclass(frozen=True)
class FactorSnapshot:
    close: float
    mid: float
    fast_ema: MaybeFloat
    slow_ema: MaybeFloat
    rsi: MaybeFloat
    atr: MaybeFloat
    breakout_high: MaybeFloat
    breakout_low: MaybeFloat

    def is_ready(self) -> bool:
        return all(
            value is not None
            for value in (
                self.fast_ema,
                self.slow_ema,
                self.rsi,
                self.atr,
                self.breakout_high,
                self.breakout_low,
            )
        )


@dataclass(frozen=True)
class FactorSeries:
    closes: list[float]
    highs: list[float]
    lows: list[float]
    mids: list[float]
    fast_ema: list[MaybeFloat]
    slow_ema: list[MaybeFloat]
    rsi: list[MaybeFloat]
    atr: list[MaybeFloat]
    breakout_high: list[MaybeFloat]
    breakout_low: list[MaybeFloat]

    def values_for(self, name: str) -> list[MaybeFloat]:
        field_name = {"close": "closes", "high": "highs", "low": "lows", "mid": "mids"}.get(name, name)
        values = getattr(self, field_name, None)
        if values is None:
            raise KeyError(f"unknown factor series '{name}'")
        return list(values)

    def latest(self) -> FactorSnapshot:
        if not self.closes:
            raise ValueError("cannot take latest factors from an empty series")
        return FactorSnapshot(
            close=self.closes[-1],
            mid=self.mids[-1],
            fast_ema=self.fast_ema[-1],
            slow_ema=self.slow_ema[-1],
            rsi=self.rsi[-1],
            atr=self.atr[-1],
            breakout_high=self.breakout_high[-1],
            breakout_low=self.breakout_low[-1],
        )


def compute_factor_series(candles: list[Candle], strategy_config: StrategyConfig) -> FactorSeries:
    closes = [candle.close for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    mids = [(candle.high + candle.low) / 2 for candle in candles]
    return FactorSeries(
        closes=closes,
        highs=highs,
        lows=lows,
        mids=mids,
        fast_ema=exponential_moving_average(closes, strategy_config.fast_ema_period),
        slow_ema=exponential_moving_average(closes, strategy_config.slow_ema_period),
        rsi=relative_strength_index(closes, strategy_config.rsi_period),
        atr=average_true_range(highs, lows, closes, strategy_config.atr_period),
        breakout_high=rolling_high(closes, strategy_config.breakout_lookback),
        breakout_low=rolling_low(closes, strategy_config.breakout_lookback),
    )