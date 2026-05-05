from __future__ import annotations

from dataclasses import dataclass

from factors.core import FactorSnapshot, MaybeFloat


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    label: str
    group: str
    description: str


@dataclass(frozen=True)
class FactorValue:
    definition: FactorDefinition
    value: MaybeFloat


class FactorRepository:
    def __init__(self, definitions: list[FactorDefinition]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}

    def definitions(self) -> list[FactorDefinition]:
        return list(self._definitions.values())

    def latest_values(self, snapshot: FactorSnapshot) -> list[FactorValue]:
        values: list[FactorValue] = []
        for definition in self.definitions():
            values.append(FactorValue(definition=definition, value=getattr(snapshot, definition.name)))
        return values


def default_factor_repository() -> FactorRepository:
    return FactorRepository(
        definitions=[
            FactorDefinition("close", "Close", "price", "Last oracle/candle close."),
            FactorDefinition("mid", "Mid", "price", "Derived candle midpoint, defined as (high + low) / 2."),
            FactorDefinition("fast_ema", "Fast EMA", "trend", "Fast EMA over close price."),
            FactorDefinition("slow_ema", "Slow EMA", "trend", "Slow EMA over close price."),
            FactorDefinition("rsi", "RSI", "momentum", "Relative Strength Index over close price."),
            FactorDefinition("atr", "ATR", "volatility", "Average True Range from high, low, and close."),
            FactorDefinition("breakout_high", "Breakout High", "level", "Rolling prior close high used for long breakout confirmation."),
            FactorDefinition("breakout_low", "Breakout Low", "level", "Rolling prior close low used for short breakdown confirmation."),
        ]
    )