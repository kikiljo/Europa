from __future__ import annotations

import math
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
    pyth_price: MaybeFloat
    pyth_confidence: MaybeFloat
    pyth_confidence_pct: MaybeFloat
    pyth_ema_confidence_pct: MaybeFloat
    pyth_confidence_slope: MaybeFloat
    pyth_confidence_gap: MaybeFloat
    cross_asset_reference_close: MaybeFloat
    cross_asset_beta: MaybeFloat
    cross_asset_corr: MaybeFloat
    cross_asset_residual: MaybeFloat
    cross_asset_reversion: MaybeFloat
    cross_asset_reversion_slope: MaybeFloat
    cross_market_eth_beta: MaybeFloat
    cross_market_btc_beta: MaybeFloat
    cross_market_corr_min: MaybeFloat
    cross_market_residual: MaybeFloat
    cross_market_reversion: MaybeFloat
    cross_market_reversion_slope: MaybeFloat

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
    pyth_price: list[MaybeFloat]
    pyth_confidence: list[MaybeFloat]
    pyth_confidence_pct: list[MaybeFloat]
    pyth_ema_confidence_pct: list[MaybeFloat]
    pyth_confidence_slope: list[MaybeFloat]
    pyth_confidence_gap: list[MaybeFloat]
    cross_asset_reference_close: list[MaybeFloat]
    cross_asset_beta: list[MaybeFloat]
    cross_asset_corr: list[MaybeFloat]
    cross_asset_residual: list[MaybeFloat]
    cross_asset_reversion: list[MaybeFloat]
    cross_asset_reversion_slope: list[MaybeFloat]
    cross_market_eth_beta: list[MaybeFloat]
    cross_market_btc_beta: list[MaybeFloat]
    cross_market_corr_min: list[MaybeFloat]
    cross_market_residual: list[MaybeFloat]
    cross_market_reversion: list[MaybeFloat]
    cross_market_reversion_slope: list[MaybeFloat]

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
            pyth_price=self.pyth_price[-1],
            pyth_confidence=self.pyth_confidence[-1],
            pyth_confidence_pct=self.pyth_confidence_pct[-1],
            pyth_ema_confidence_pct=self.pyth_ema_confidence_pct[-1],
            pyth_confidence_slope=self.pyth_confidence_slope[-1],
            pyth_confidence_gap=self.pyth_confidence_gap[-1],
            cross_asset_reference_close=self.cross_asset_reference_close[-1],
            cross_asset_beta=self.cross_asset_beta[-1],
            cross_asset_corr=self.cross_asset_corr[-1],
            cross_asset_residual=self.cross_asset_residual[-1],
            cross_asset_reversion=self.cross_asset_reversion[-1],
            cross_asset_reversion_slope=self.cross_asset_reversion_slope[-1],
            cross_market_eth_beta=self.cross_market_eth_beta[-1],
            cross_market_btc_beta=self.cross_market_btc_beta[-1],
            cross_market_corr_min=self.cross_market_corr_min[-1],
            cross_market_residual=self.cross_market_residual[-1],
            cross_market_reversion=self.cross_market_reversion[-1],
            cross_market_reversion_slope=self.cross_market_reversion_slope[-1],
        )


def compute_factor_series(
    candles: list[Candle],
    strategy_config: StrategyConfig,
    reference_candles: list[Candle] | None = None,
    reference_candles_by_name: dict[str, list[Candle]] | None = None,
    cross_asset_lookback: int = 96,
    cross_market_lookback: int = 96,
) -> FactorSeries:
    closes = [candle.close for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    mids = [(candle.high + candle.low) / 2 for candle in candles]
    reference_closes = _aligned_reference_closes(candles, reference_candles)
    named_reference_closes = {
        name.upper(): _aligned_reference_closes(candles, named_candles)
        for name, named_candles in (reference_candles_by_name or {}).items()
    }
    eth_closes = named_reference_closes.get("ETH", [None] * len(candles))
    btc_closes = named_reference_closes.get("BTC", [None] * len(candles))
    pyth_price = [candle.pyth_price for candle in candles]
    pyth_confidence = [candle.pyth_confidence for candle in candles]
    pyth_ema_confidence = [candle.pyth_ema_confidence for candle in candles]
    fast_ema = exponential_moving_average(closes, strategy_config.fast_ema_period)
    slow_ema = exponential_moving_average(closes, strategy_config.slow_ema_period)
    rsi = relative_strength_index(closes, strategy_config.rsi_period)
    atr = average_true_range(highs, lows, closes, strategy_config.atr_period)
    pyth_confidence_pct = _ratio_pct(pyth_confidence, closes)
    pyth_ema_confidence_pct = _ratio_pct(pyth_ema_confidence, closes)
    cross_asset_beta, cross_asset_residual, cross_asset_reversion = _rolling_cross_asset_regression(
        closes,
        reference_closes,
        lookback=cross_asset_lookback,
    )
    cross_market_eth_beta, cross_market_btc_beta, cross_market_residual, cross_market_reversion = _rolling_cross_market_regression(
        closes,
        eth_closes,
        btc_closes,
        lookback=cross_market_lookback,
    )
    sol_eth_corr = _rolling_return_corr(closes, eth_closes, lookback=cross_market_lookback)
    sol_btc_corr = _rolling_return_corr(closes, btc_closes, lookback=cross_market_lookback)
    eth_btc_corr = _rolling_optional_return_corr(eth_closes, btc_closes, lookback=cross_market_lookback)
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
        pyth_price=pyth_price,
        pyth_confidence=pyth_confidence,
        pyth_confidence_pct=pyth_confidence_pct,
        pyth_ema_confidence_pct=pyth_ema_confidence_pct,
        pyth_confidence_slope=_relative_change(pyth_confidence_pct, lookback=4),
        pyth_confidence_gap=_optional_difference(pyth_confidence_pct, pyth_ema_confidence_pct),
        cross_asset_reference_close=reference_closes,
        cross_asset_beta=cross_asset_beta,
        cross_asset_corr=_rolling_return_corr(closes, reference_closes, lookback=cross_asset_lookback),
        cross_asset_residual=cross_asset_residual,
        cross_asset_reversion=cross_asset_reversion,
        cross_asset_reversion_slope=_difference(cross_asset_reversion, lookback=4),
        cross_market_eth_beta=cross_market_eth_beta,
        cross_market_btc_beta=cross_market_btc_beta,
        cross_market_corr_min=_min_optional_series(sol_eth_corr, sol_btc_corr, eth_btc_corr),
        cross_market_residual=cross_market_residual,
        cross_market_reversion=cross_market_reversion,
        cross_market_reversion_slope=_difference(cross_market_reversion, lookback=4),
    )


def _aligned_reference_closes(candles: list[Candle], reference_candles: list[Candle] | None) -> list[MaybeFloat]:
    if reference_candles is None:
        return [None] * len(candles)
    closes_by_timestamp = {candle.timestamp: candle.close for candle in reference_candles}
    return [closes_by_timestamp.get(candle.timestamp) for candle in candles]


def _rolling_cross_asset_regression(
    closes: list[float],
    reference_closes: list[MaybeFloat],
    *,
    lookback: int,
) -> tuple[list[MaybeFloat], list[MaybeFloat], list[MaybeFloat]]:
    betas: list[MaybeFloat] = []
    residuals: list[MaybeFloat] = []
    reversions: list[MaybeFloat] = []
    for index in range(len(closes)):
        start = index - lookback + 1
        if start < 0:
            betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        window = [
            (math.log(reference_closes[pos]), math.log(closes[pos]))
            for pos in range(start, index + 1)
            if reference_closes[pos] is not None and reference_closes[pos] > 0 and closes[pos] > 0
        ]
        if len(window) != lookback:
            betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        x_values = [pair[0] for pair in window]
        y_values = [pair[1] for pair in window]
        x_mean = sum(x_values) / lookback
        y_mean = sum(y_values) / lookback
        x_variance = sum((value - x_mean) ** 2 for value in x_values)
        if x_variance == 0:
            betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        beta = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, y_values)) / x_variance
        alpha = y_mean - beta * x_mean
        window_residuals = [y_value - (alpha + beta * x_value) for x_value, y_value in zip(x_values, y_values)]
        residual_mean = sum(window_residuals) / lookback
        residual_variance = sum((value - residual_mean) ** 2 for value in window_residuals)
        residual_stdev = math.sqrt(residual_variance / (lookback - 1)) if lookback > 1 else 0.0
        if residual_stdev == 0:
            betas.append(beta)
            residuals.append(window_residuals[-1])
            reversions.append(None)
            continue
        residual_z = (window_residuals[-1] - residual_mean) / residual_stdev
        betas.append(beta)
        residuals.append(window_residuals[-1])
        reversions.append(-residual_z)
    return betas, residuals, reversions


def _rolling_cross_market_regression(
    closes: list[float],
    eth_closes: list[MaybeFloat],
    btc_closes: list[MaybeFloat],
    *,
    lookback: int,
) -> tuple[list[MaybeFloat], list[MaybeFloat], list[MaybeFloat], list[MaybeFloat]]:
    eth_betas: list[MaybeFloat] = []
    btc_betas: list[MaybeFloat] = []
    residuals: list[MaybeFloat] = []
    reversions: list[MaybeFloat] = []
    for index in range(len(closes)):
        start = index - lookback + 1
        if start < 0:
            eth_betas.append(None)
            btc_betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        window = [
            (math.log(eth_closes[pos]), math.log(btc_closes[pos]), math.log(closes[pos]))
            for pos in range(start, index + 1)
            if eth_closes[pos] is not None
            and btc_closes[pos] is not None
            and eth_closes[pos] > 0
            and btc_closes[pos] > 0
            and closes[pos] > 0
        ]
        if len(window) != lookback:
            eth_betas.append(None)
            btc_betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        eth_logs = [item[0] for item in window]
        btc_logs = [item[1] for item in window]
        sol_logs = [item[2] for item in window]
        eth_mean = sum(eth_logs) / lookback
        btc_mean = sum(btc_logs) / lookback
        sol_mean = sum(sol_logs) / lookback
        eth_var = sum((value - eth_mean) ** 2 for value in eth_logs)
        btc_var = sum((value - btc_mean) ** 2 for value in btc_logs)
        eth_btc_cov = sum((eth_value - eth_mean) * (btc_value - btc_mean) for eth_value, btc_value in zip(eth_logs, btc_logs))
        sol_eth_cov = sum((eth_value - eth_mean) * (sol_value - sol_mean) for eth_value, sol_value in zip(eth_logs, sol_logs))
        sol_btc_cov = sum((btc_value - btc_mean) * (sol_value - sol_mean) for btc_value, sol_value in zip(btc_logs, sol_logs))
        determinant = eth_var * btc_var - eth_btc_cov**2
        if determinant == 0:
            eth_betas.append(None)
            btc_betas.append(None)
            residuals.append(None)
            reversions.append(None)
            continue
        eth_beta = (sol_eth_cov * btc_var - sol_btc_cov * eth_btc_cov) / determinant
        btc_beta = (sol_btc_cov * eth_var - sol_eth_cov * eth_btc_cov) / determinant
        alpha = sol_mean - eth_beta * eth_mean - btc_beta * btc_mean
        window_residuals = [
            sol_value - (alpha + eth_beta * eth_value + btc_beta * btc_value)
            for eth_value, btc_value, sol_value in zip(eth_logs, btc_logs, sol_logs)
        ]
        residual_mean = sum(window_residuals) / lookback
        residual_variance = sum((value - residual_mean) ** 2 for value in window_residuals)
        residual_stdev = math.sqrt(residual_variance / (lookback - 1)) if lookback > 1 else 0.0
        eth_betas.append(eth_beta)
        btc_betas.append(btc_beta)
        residuals.append(window_residuals[-1])
        reversions.append(None if residual_stdev == 0 else -((window_residuals[-1] - residual_mean) / residual_stdev))
    return eth_betas, btc_betas, residuals, reversions


def _rolling_return_corr(closes: list[float], reference_closes: list[MaybeFloat], *, lookback: int) -> list[MaybeFloat]:
    return _rolling_optional_return_corr([close for close in closes], reference_closes, lookback=lookback)


def _rolling_optional_return_corr(left_closes: list[MaybeFloat], right_closes: list[MaybeFloat], *, lookback: int) -> list[MaybeFloat]:
    returns: list[MaybeFloat] = [None]
    reference_returns: list[MaybeFloat] = [None]
    for index in range(1, len(left_closes)):
        left_now = left_closes[index]
        left_previous = left_closes[index - 1]
        right_now = right_closes[index]
        right_previous = right_closes[index - 1]
        if left_previous is None or left_now is None or right_previous is None or right_now is None or left_previous <= 0 or left_now <= 0 or right_previous <= 0 or right_now <= 0:
            returns.append(None)
            reference_returns.append(None)
        else:
            returns.append(math.log(left_now / left_previous))
            reference_returns.append(math.log(right_now / right_previous))

    correlations: list[MaybeFloat] = []
    for index in range(len(left_closes)):
        start = index - lookback + 1
        if start < 1:
            correlations.append(None)
            continue
        left_window = returns[start : index + 1]
        right_window = reference_returns[start : index + 1]
        if any(value is None for value in left_window) or any(value is None for value in right_window):
            correlations.append(None)
            continue
        correlations.append(_correlation([float(value) for value in left_window], [float(value) for value in right_window]))
    return correlations


def _min_optional_series(*series_collection: list[MaybeFloat]) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for values in zip(*series_collection):
        if any(value is None for value in values):
            output.append(None)
        else:
            output.append(min(float(value) for value in values))
    return output


def _correlation(left: list[float], right: list[float]) -> MaybeFloat:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((left_value - left_mean) * (right_value - right_mean) for left_value, right_value in zip(left, right))
    left_denominator = math.sqrt(sum((left_value - left_mean) ** 2 for left_value in left))
    right_denominator = math.sqrt(sum((right_value - right_mean) ** 2 for right_value in right))
    if left_denominator == 0 or right_denominator == 0:
        return None
    return numerator / (left_denominator * right_denominator)


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


def _optional_difference(left: list[MaybeFloat], right: list[MaybeFloat]) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for left_value, right_value in zip(left, right):
        if left_value is None or right_value is None:
            output.append(None)
        else:
            output.append(left_value - right_value)
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