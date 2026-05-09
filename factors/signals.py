from __future__ import annotations

from factors.core import FactorSeries
from factors.repository import FactorRepository, default_factor_repository
from trading.signals import ResearchSignal, expanding_zscore_normalize


DEFAULT_FACTOR_SIGNAL_NAMES = [
    "fast_ema_slope",
    "slow_ema_slope",
    "ema_spread",
    "price_vs_slow_ema",
    "rsi_momentum",
    "rsi_reversion",
    "rsi_slope",
]


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
                values=expanding_zscore_normalize(raw_values),
                description=definition.description,
                normalization="expanding_zscore_30",
            )
        )
    return signals