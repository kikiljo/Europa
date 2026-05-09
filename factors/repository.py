from __future__ import annotations

from dataclasses import dataclass

from factors.core import FactorSnapshot, MaybeFloat


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    label: str
    group: str
    description: str
    family: str = ""
    family_label: str = ""


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
            FactorDefinition("fast_ema", "Fast EMA", "trend", "Fast EMA over close price.", family="ema", family_label="EMA"),
            FactorDefinition("slow_ema", "Slow EMA", "trend", "Slow EMA over close price.", family="ema", family_label="EMA"),
            FactorDefinition("fast_ema_slope", "Fast EMA Slope", "trend", "Fast EMA relative change over the last 4 ticks.", family="ema", family_label="EMA"),
            FactorDefinition("slow_ema_slope", "Slow EMA Slope", "trend", "Slow EMA relative change over the last 4 ticks.", family="ema", family_label="EMA"),
            FactorDefinition("ema_spread", "EMA Spread", "trend", "Fast EMA minus slow EMA, divided by close.", family="ema", family_label="EMA"),
            FactorDefinition("price_vs_fast_ema", "Price vs Fast EMA", "trend", "Close minus fast EMA, divided by fast EMA.", family="ema", family_label="EMA"),
            FactorDefinition("price_vs_slow_ema", "Price vs Slow EMA", "trend", "Close minus slow EMA, divided by slow EMA.", family="ema", family_label="EMA"),
            FactorDefinition("rsi", "RSI", "momentum", "Relative Strength Index over close price.", family="rsi", family_label="RSI"),
            FactorDefinition("rsi_momentum", "RSI Momentum", "momentum", "RSI centered at 50; high RSI is positive momentum.", family="rsi", family_label="RSI"),
            FactorDefinition("rsi_reversion", "RSI Reversion", "momentum", "RSI centered at 50 and inverted; low RSI is positive mean-reversion pressure.", family="rsi", family_label="RSI"),
            FactorDefinition("rsi_slope", "RSI Slope", "momentum", "RSI point change over the last 4 ticks.", family="rsi", family_label="RSI"),
            FactorDefinition("atr", "ATR", "volatility", "Average True Range from high, low, and close.", family="atr", family_label="ATR"),
            FactorDefinition("atr_pct", "ATR %", "volatility", "ATR divided by close; volatility scale, not a directional signal.", family="atr", family_label="ATR"),
            FactorDefinition("breakout_high", "Breakout High", "level", "Rolling prior close high used for long breakout confirmation.", family="breakout", family_label="Breakout"),
            FactorDefinition("breakout_low", "Breakout Low", "level", "Rolling prior close low used for short breakdown confirmation.", family="breakout", family_label="Breakout"),
            FactorDefinition("pyth_price", "Pyth Price", "oracle", "Hermes price sampled near the candle close.", family="pyth", family_label="Pyth"),
            FactorDefinition("pyth_confidence", "Pyth Confidence", "oracle", "Pyth confidence interval in price units; higher means more oracle uncertainty.", family="pyth", family_label="Pyth"),
            FactorDefinition("pyth_confidence_pct", "Pyth Confidence %", "oracle", "Pyth confidence divided by close; an oracle uncertainty scale, not a directional signal.", family="pyth", family_label="Pyth"),
            FactorDefinition("pyth_ema_confidence_pct", "Pyth EMA Confidence %", "oracle", "Pyth EMA confidence divided by close; smoother oracle uncertainty scale.", family="pyth", family_label="Pyth"),
            FactorDefinition("pyth_confidence_slope", "Pyth Confidence Slope", "oracle", "Relative change in Pyth confidence percentage over the last 4 ticks.", family="pyth", family_label="Pyth"),
            FactorDefinition("pyth_confidence_gap", "Pyth Confidence Gap", "oracle", "Raw confidence percentage minus EMA confidence percentage.", family="pyth", family_label="Pyth"),
            FactorDefinition("cross_asset_reference_close", "Reference Close", "cross_asset", "Reference market close aligned to the primary candle timestamp.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_asset_beta", "Cross-Asset Beta", "cross_asset", "Rolling 96-tick log-price regression beta of primary market versus reference market.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_asset_corr", "Cross-Asset Corr", "cross_asset", "Rolling 96-tick correlation of primary and reference log returns.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_asset_residual", "Cross-Asset Residual", "cross_asset", "Current log-price regression residual versus the reference market.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_asset_reversion", "Cross-Asset Reversion", "cross_asset", "Negative rolling residual z-score; positive means the primary market is cheap versus the reference market.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_asset_reversion_slope", "Cross-Asset Reversion Slope", "cross_asset", "Four-tick change in the cross-asset reversion signal.", family="cross_asset", family_label="Cross Asset"),
            FactorDefinition("cross_market_eth_beta", "Cross-Market ETH Beta", "cross_market", "Rolling 96-tick basket regression beta of the primary market versus ETH.", family="cross_market", family_label="Cross Market"),
            FactorDefinition("cross_market_btc_beta", "Cross-Market BTC Beta", "cross_market", "Rolling 96-tick basket regression beta of the primary market versus BTC.", family="cross_market", family_label="Cross Market"),
            FactorDefinition("cross_market_corr_min", "Cross-Market Corr Min", "cross_market", "Minimum rolling 96-tick return correlation across SOL-ETH, SOL-BTC, and ETH-BTC; higher means the basket relationship is cleaner.", family="cross_market", family_label="Cross Market"),
            FactorDefinition("cross_market_residual", "Cross-Market Residual", "cross_market", "Current log-price basket regression residual versus ETH and BTC together.", family="cross_market", family_label="Cross Market"),
            FactorDefinition("cross_market_reversion", "Cross-Market Reversion", "cross_market", "Negative rolling basket residual z-score; positive means the primary market is cheap versus the ETH+BTC basket.", family="cross_market", family_label="Cross Market"),
            FactorDefinition("cross_market_reversion_slope", "Cross-Market Reversion Slope", "cross_market", "Four-tick change in the cross-market reversion signal.", family="cross_market", family_label="Cross Market"),
        ]
    )
