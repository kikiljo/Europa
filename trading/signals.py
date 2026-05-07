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


@dataclass(frozen=True)
class DecileSpreadResult:
    signal_name: str
    signal_label: str
    signal_source: str
    horizon: int
    sample_size: int
    bottom_mean_value: MaybeFloat
    top_mean_value: MaybeFloat
    mean_value: MaybeFloat
    difference_value: MaybeFloat


@dataclass(frozen=True)
class TailEventSummary:
    signal_name: str
    signal_label: str
    signal_source: str
    tail: str
    count: int
    total_observations: int
    share_pct: float
    mean_signal: MaybeFloat
    mean_close: MaybeFloat
    mean_one_tick_price_change: MaybeFloat
    mean_lookback_price_change: MaybeFloat
    mean_range_price: MaybeFloat
    forward_mean_directional_price_changes: dict[int, MaybeFloat]


@dataclass(frozen=True)
class TailEventPoint:
    signal_name: str
    signal_label: str
    signal_source: str
    tail: str
    timestamp_index: int
    signal_value: float


def expanding_zscore_normalize(values: list[MaybeFloat], *, min_observations: int = 30) -> list[MaybeFloat]:
    if min_observations < 2:
        raise ValueError("min_observations must be at least 2")

    normalized: list[MaybeFloat] = []
    count = 0
    mean_value = 0.0
    m2 = 0.0
    for value in values:
        if value is None:
            normalized.append(None)
            continue

        if count < min_observations or m2 <= 0:
            normalized.append(None)
        else:
            variance = m2 / count
            stdev = variance**0.5
            normalized.append(0.0 if stdev == 0 else (value - mean_value) / stdev)

        count += 1
        delta = value - mean_value
        mean_value += delta / count
        delta2 = value - mean_value
        m2 += delta * delta2
    return normalized


def zscore_normalize(values: list[MaybeFloat]) -> list[MaybeFloat]:
    return expanding_zscore_normalize(values)


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


def future_price_changes(candles: list[Candle], horizons: list[int]) -> dict[int, list[MaybeFloat]]:
    closes = [candle.close for candle in candles]
    output: dict[int, list[MaybeFloat]] = {}
    for horizon in horizons:
        changes: list[MaybeFloat] = []
        for index, close in enumerate(closes):
            future_index = index + horizon
            if future_index >= len(closes):
                changes.append(None)
            else:
                changes.append(closes[future_index] - close)
        output[horizon] = changes
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


def signal_forward_value_decile_comparisons(
    signals: list[ResearchSignal],
    forward_values: dict[int, list[MaybeFloat]],
    *,
    tail_fraction: float = 0.10,
) -> list[DecileSpreadResult]:
    if tail_fraction <= 0 or tail_fraction >= 0.5:
        raise ValueError("tail_fraction must be greater than 0 and less than 0.5")

    results: list[DecileSpreadResult] = []
    for signal in signals:
        for horizon, values in forward_values.items():
            pairs = sorted(_paired_values(signal.values, values), key=lambda pair: pair[0])
            bucket_size = int(len(pairs) * tail_fraction)
            if bucket_size < 1:
                results.append(
                    DecileSpreadResult(
                        signal_name=signal.name,
                        signal_label=signal.label,
                        signal_source=signal.source,
                        horizon=horizon,
                        sample_size=len(pairs),
                        bottom_mean_value=None,
                        top_mean_value=None,
                        mean_value=None,
                        difference_value=None,
                    )
                )
                continue

            bottom_values = [_directional_value(pair[0], pair[1]) for pair in pairs[:bucket_size]]
            top_values = [_directional_value(pair[0], pair[1]) for pair in pairs[-bucket_size:]]
            bottom_mean = sum(bottom_values) / len(bottom_values)
            top_mean = sum(top_values) / len(top_values)
            mean_value = sum(bottom_values + top_values) / (len(bottom_values) + len(top_values))
            results.append(
                DecileSpreadResult(
                    signal_name=signal.name,
                    signal_label=signal.label,
                    signal_source=signal.source,
                    horizon=horizon,
                    sample_size=len(pairs),
                    bottom_mean_value=bottom_mean,
                    top_mean_value=top_mean,
                    mean_value=mean_value,
                    difference_value=top_mean - bottom_mean,
                )
            )
    return results


def signal_tail_events(
    signals: list[ResearchSignal],
    candles: list[Candle],
    forward_price_changes: dict[int, list[MaybeFloat]],
    *,
    tail_fraction: float = 0.01,
    lookback_ticks: int = 48,
) -> tuple[list[TailEventSummary], list[TailEventPoint]]:
    if tail_fraction <= 0 or tail_fraction >= 0.5:
        raise ValueError("tail_fraction must be greater than 0 and less than 0.5")
    if lookback_ticks <= 0:
        raise ValueError("lookback_ticks must be positive")

    summaries: list[TailEventSummary] = []
    points: list[TailEventPoint] = []
    closes = [candle.close for candle in candles]
    ranges = [candle.high - candle.low for candle in candles]
    one_tick_price_changes = _lookback_price_changes(closes, 1)
    lookback_price_changes = _lookback_price_changes(closes, lookback_ticks)

    for signal in signals:
        indexed_values = [(index, value) for index, value in enumerate(signal.values) if value is not None and index < len(candles)]
        indexed_values.sort(key=lambda item: item[1])
        tail_count = max(1, int(len(indexed_values) * tail_fraction)) if indexed_values else 0
        tail_sets = (
            ("bottom", indexed_values[:tail_count]),
            ("top", indexed_values[-tail_count:]),
        )
        for tail_name, tail_values in tail_sets:
            event_indices = [index for index, _ in tail_values]
            signal_values = [value for _, value in tail_values]
            for event_index, signal_value in tail_values:
                points.append(
                    TailEventPoint(
                        signal_name=signal.name,
                        signal_label=signal.label,
                        signal_source=signal.source,
                        tail=tail_name,
                        timestamp_index=event_index,
                        signal_value=signal_value,
                    )
                )
            summaries.append(
                TailEventSummary(
                    signal_name=signal.name,
                    signal_label=signal.label,
                    signal_source=signal.source,
                    tail=tail_name,
                    count=len(tail_values),
                    total_observations=len(indexed_values),
                    share_pct=(len(tail_values) / len(indexed_values) * 100) if indexed_values else 0.0,
                    mean_signal=_mean(signal_values),
                    mean_close=_mean([closes[index] for index in event_indices]),
                    mean_one_tick_price_change=_mean([one_tick_price_changes[index] for index in event_indices if one_tick_price_changes[index] is not None]),
                    mean_lookback_price_change=_mean([lookback_price_changes[index] for index in event_indices if lookback_price_changes[index] is not None]),
                    mean_range_price=_mean([ranges[index] for index in event_indices]),
                    forward_mean_directional_price_changes={
                        horizon: _mean([
                            _directional_value(signal_value, changes[index])
                            for index, signal_value in tail_values
                            if index < len(changes) and changes[index] is not None
                        ])
                        for horizon, changes in forward_price_changes.items()
                    },
                )
            )
    return summaries, points


def _paired_values(left: list[MaybeFloat], right: list[MaybeFloat]) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for left_value, right_value in zip(left, right):
        if left_value is not None and right_value is not None:
            pairs.append((left_value, right_value))
    return pairs


def _lookback_price_changes(values: list[float], lookback_ticks: int) -> list[MaybeFloat]:
    output: list[MaybeFloat] = []
    for index, value in enumerate(values):
        previous_index = index - lookback_ticks
        if previous_index < 0:
            output.append(None)
        else:
            output.append(value - values[previous_index])
    return output


def _mean(values: list[float]) -> MaybeFloat:
    if not values:
        return None
    return sum(values) / len(values)


def _directional_value(signal_value: float, forward_value: float) -> float:
    if signal_value > 0:
        return forward_value
    if signal_value < 0:
        return -forward_value
    return 0.0


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