from __future__ import annotations

from dataclasses import dataclass

from trading.domain import Candle


MaybeFloat = float | None


@dataclass(frozen=True)
class ResearchSignal:
    name: str
    label: str
    source: str
    group: str
    raw_values: list[MaybeFloat]
    values: list[MaybeFloat]
    description: str = ""
    normalization: str = "none"

    def latest_value(self) -> MaybeFloat:
        for value in reversed(self.values):
            if value is not None:
                return value
        return None


@dataclass(frozen=True)
class SignalSummary:
    name: str
    label: str
    source: str
    group: str
    count: int
    latest: MaybeFloat
    mean: MaybeFloat
    stdev: MaybeFloat
    minimum: MaybeFloat
    maximum: MaybeFloat
    normalization: str


@dataclass(frozen=True)
class CorrelationResult:
    signal_name: str
    signal_label: str
    signal_source: str
    horizon: int
    sample_size: int
    correlation: MaybeFloat


def zscore_normalize(values: list[MaybeFloat]) -> list[MaybeFloat]:
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return [None] * len(values)
    mean_value = sum(clean_values) / len(clean_values)
    variance = sum((value - mean_value) ** 2 for value in clean_values) / len(clean_values)
    stdev = variance**0.5
    if stdev == 0:
        return [0.0 if value is not None else None for value in values]
    return [None if value is None else (value - mean_value) / stdev for value in values]


def future_returns(candles: list[Candle], horizons: list[int]) -> dict[int, list[MaybeFloat]]:
    closes = [candle.close for candle in candles]
    output: dict[int, list[MaybeFloat]] = {}
    for horizon in horizons:
        returns: list[MaybeFloat] = []
        for index, close in enumerate(closes):
            future_index = index + horizon
            if close == 0 or future_index >= len(closes):
                returns.append(None)
            else:
                returns.append(closes[future_index] / close - 1)
        output[horizon] = returns
    return output


def summarize_signals(signals: list[ResearchSignal]) -> list[SignalSummary]:
    summaries: list[SignalSummary] = []
    for signal in signals:
        values = [value for value in signal.values if value is not None]
        if values:
            mean_value = sum(values) / len(values)
            variance = sum((value - mean_value) ** 2 for value in values) / len(values)
            stdev = variance**0.5
            minimum = min(values)
            maximum = max(values)
        else:
            mean_value = None
            stdev = None
            minimum = None
            maximum = None
        summaries.append(
            SignalSummary(
                name=signal.name,
                label=signal.label,
                source=signal.source,
                group=signal.group,
                count=len(values),
                latest=signal.latest_value(),
                mean=mean_value,
                stdev=stdev,
                minimum=minimum,
                maximum=maximum,
                normalization=signal.normalization,
            )
        )
    return summaries


def signal_forward_return_correlations(
    signals: list[ResearchSignal],
    forward_returns: dict[int, list[MaybeFloat]],
) -> list[CorrelationResult]:
    results: list[CorrelationResult] = []
    for signal in signals:
        for horizon, returns in forward_returns.items():
            pairs = _paired_values(signal.values, returns)
            correlation = _pearson([pair[0] for pair in pairs], [pair[1] for pair in pairs]) if len(pairs) >= 3 else None
            results.append(
                CorrelationResult(
                    signal_name=signal.name,
                    signal_label=signal.label,
                    signal_source=signal.source,
                    horizon=horizon,
                    sample_size=len(pairs),
                    correlation=correlation,
                )
            )
    return results


def _paired_values(left: list[MaybeFloat], right: list[MaybeFloat]) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for left_value, right_value in zip(left, right):
        if left_value is not None and right_value is not None:
            pairs.append((left_value, right_value))
    return pairs


def _pearson(left: list[float], right: list[float]) -> MaybeFloat:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((left_value - left_mean) * (right_value - right_mean) for left_value, right_value in zip(left, right))
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    denominator = (left_var * right_var) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator