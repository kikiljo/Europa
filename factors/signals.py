from __future__ import annotations

from factors.core import FactorSeries
from factors.repository import FactorRepository, default_factor_repository
from trading.signals import ResearchSignal, zscore_normalize


DEFAULT_FACTOR_SIGNAL_NAMES = ["fast_ema", "slow_ema", "rsi", "atr", "breakout_high", "breakout_low"]


def build_factor_signals(
    factor_series: FactorSeries,
    *,
    repository: FactorRepository | None = None,
    names: list[str] | None = None,
) -> list[ResearchSignal]:
    repo = repository or default_factor_repository()
    selected_names = names or DEFAULT_FACTOR_SIGNAL_NAMES
    definitions = {definition.name: definition for definition in repo.definitions()}
    signals: list[ResearchSignal] = []
    for name in selected_names:
        definition = definitions.get(name)
        if definition is None:
            continue
        raw_values = factor_series.values_for(name)
        signals.append(
            ResearchSignal(
                name=f"factor_{name}",
                label=definition.label,
                source="factor",
                group=definition.group,
                raw_values=raw_values,
                values=zscore_normalize(raw_values),
                description=definition.description,
                normalization="zscore",
            )
        )
    return signals