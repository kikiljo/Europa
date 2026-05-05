from __future__ import annotations


def simple_moving_average(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period <= 0:
        raise ValueError("period must be positive")
    rolling_sum = 0.0
    for index, value in enumerate(values):
        rolling_sum += value
        if index >= period:
            rolling_sum -= values[index - period]
        if index >= period - 1:
            output[index] = rolling_sum / period
    return output


def exponential_moving_average(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return output
    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    output[period - 1] = seed
    previous_ema = seed
    for index in range(period, len(values)):
        previous_ema = (values[index] - previous_ema) * multiplier + previous_ema
        output[index] = previous_ema
    return output


def relative_strength_index(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) <= period:
        return output
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    output[period] = _rsi_from_averages(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
        output[index] = _rsi_from_averages(average_gain, average_loss)
    return output


def _rsi_from_averages(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - 100 / (1 + relative_strength)


def average_true_range(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(closes)
    if period <= 0:
        raise ValueError("period must be positive")
    if not closes or len(closes) != len(highs) or len(closes) != len(lows):
        raise ValueError("highs, lows, and closes must be the same non-zero length")
    true_ranges: list[float] = []
    for index, close in enumerate(closes):
        if index == 0:
            true_range = highs[index] - lows[index]
        else:
            previous_close = closes[index - 1]
            true_range = max(
                highs[index] - lows[index],
                abs(highs[index] - previous_close),
                abs(lows[index] - previous_close),
            )
        true_ranges.append(true_range)
    if len(true_ranges) < period:
        return output
    average_range = sum(true_ranges[:period]) / period
    output[period - 1] = average_range
    for index in range(period, len(true_ranges)):
        average_range = (average_range * (period - 1) + true_ranges[index]) / period
        output[index] = average_range
    return output


def rolling_high(values: list[float], lookback: int) -> list[float | None]:
    return _rolling_extreme(values, lookback, highest=True)


def rolling_low(values: list[float], lookback: int) -> list[float | None]:
    return _rolling_extreme(values, lookback, highest=False)


def _rolling_extreme(values: list[float], lookback: int, highest: bool) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    for index in range(lookback, len(values)):
        window = values[index - lookback : index]
        output[index] = max(window) if highest else min(window)
    return output
