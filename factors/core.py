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
    fast_ema_slope: MaybeFloat
    slow_ema_slope: MaybeFloat
    ema_spread: MaybeFloat
    price_vs_fast_ema: MaybeFloat
    price_vs_slow_ema: MaybeFloat
    rsi: MaybeFloat
    rsi_momentum: MaybeFloat
    rsi_reversion: MaybeFloat
    rsi_slope: MaybeFloat
    atr: MaybeFloat
    atr_pct: MaybeFloat
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
    fast_ema_slope: list[MaybeFloat]
    slow_ema_slope: list[MaybeFloat]
    ema_spread: list[MaybeFloat]
    price_vs_fast_ema: list[MaybeFloat]
    price_vs_slow_ema: list[MaybeFloat]
    rsi: list[MaybeFloat]
    rsi_momentum: list[MaybeFloat]
    rsi_reversion: list[MaybeFloat]
    rsi_slope: list[MaybeFloat]
    atr: list[MaybeFloat]
    atr_pct: list[MaybeFloat]
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
            fast_ema_slope=self.fast_ema_slope[-1],
            slow_ema_slope=self.slow_ema_slope[-1],
            ema_spread=self.ema_spread[-1],
            price_vs_fast_ema=self.price_vs_fast_ema[-1],
            price_vs_slow_ema=self.price_vs_slow_ema[-1],
            rsi=self.rsi[-1],
            rsi_momentum=self.rsi_momentum[-1],
            rsi_reversion=self.rsi_reversion[-1],
            rsi_slope=self.rsi_slope[-1],
            atr=self.atr[-1],
            atr_pct=self.atr_pct[-1],
            breakout_high=self.breakout_high[-1],
            breakout_low=self.breakout_low[-1],
        )


def compute_factor_series(candles: list[Candle], strategy_config: StrategyConfig) -> FactorSeries:
    closes = [candle.close for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    mids = [(candle.high + candle.low) / 2 for candle in candles]
    fast_ema = exponential_moving_average(closes, strategy_config.fast_ema_period)
    slow_ema = exponential_moving_average(closes, strategy_config.slow_ema_period)
    rsi = relative_strength_index(closes, strategy_config.rsi_period)
    atr = average_true_range(highs, lows, closes, strategy_config.atr_period)
    return FactorSeries(
        closes=closes,
        highs=highs,
        lows=lows,
        mids=mids,
        fast_ema=fast_ema,
        slow_ema=slow_ema,
        fast_ema_slope=_relative_change(fast_ema, lookback=4),
        slow_ema_slope=_relative_change(slow_ema, lookback=4),
        ema_spread=_spread_pct(fast_ema, slow_ema, closes),
        price_vs_fast_ema=_distance_pct(closes, fast_ema),
        price_vs_slow_ema=_distance_pct(closes, slow_ema),
        rsi=rsi,
        rsi_momentum=_rsi_momentum(rsi),
        rsi_reversion=_rsi_reversion(rsi),
        rsi_slope=_difference(rsi, lookback=4),
        atr=atr,
        atr_pct=_ratio_pct(atr, closes),
        breakout_high=rolling_high(closes, strategy_config.breakout_lookback),
        breakout_low=rolling_low(closes, strategy_config.breakout_lookback),
    )


def _relative_change(values: list[MaybeFloat], *, lookback: int) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for index, value in enumerate(values):
        previous_index = index - lookback
        if value is None or previous_index < 0 or values[previous_index] in (None, 0):
            output.append(None)
        else:
            previous = values[previous_index]
            assert previous is not None
            output.append(value / previous - 1)
    return output


def _difference(values: list[MaybeFloat], *, lookback: int) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for index, value in enumerate(values):
        previous_index = index - lookback
        if value is None or previous_index < 0 or values[previous_index] is None:
            output.append(None)
        else:
            previous = values[previous_index]
            assert previous is not None
            output.append(value - previous)
    return output


def _spread_pct(left: list[MaybeFloat], right: list[MaybeFloat], denominator: list[float]) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for left_value, right_value, denom in zip(left, right, denominator):
        if left_value is None or right_value is None or denom == 0:
            output.append(None)
        else:
            output.append((left_value - right_value) / denom)
    return output


def _distance_pct(left: list[float], right: list[MaybeFloat]) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for left_value, right_value in zip(left, right):
        if right_value in (None, 0):
            output.append(None)
        else:
            assert right_value is not None
            output.append((left_value - right_value) / right_value)
    return output


def _ratio_pct(left: list[MaybeFloat], right: list[float]) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for left_value, right_value in zip(left, right):
        if left_value is None or right_value == 0:
            output.append(None)
        else:
            output.append(left_value / right_value)
    return output


def _rsi_momentum(values: list[MaybeFloat]) -> list[MaybeFloat]:
    return [None if value is None else (value - 50.0) / 50.0 for value in values]


def _rsi_reversion(values: list[MaybeFloat]) -> list[MaybeFloat]:
    return [None if value is None else (50.0 - value) / 50.0 for value in values]