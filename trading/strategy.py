from __future__ import annotations

from trading.config import RiskConfig, StrategyConfig
from trading.factors import compute_factor_series
from trading.models import Candle, Position, Side, Signal, SignalAction


class SwingPerpsStrategy:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig) -> None:
        self.strategy_config = strategy_config
        self.risk_config = risk_config

    def analyze(
        self,
        candles: list[Candle],
        open_position: Position | None = None,
        weekly_trade_count: int = 0,
        last_trade_index: int | None = None,
    ) -> Signal:
        minimum_bars = max(
            self.strategy_config.slow_ema_period,
            self.strategy_config.breakout_lookback,
            self.strategy_config.rsi_period,
            self.strategy_config.atr_period,
        ) + 2
        if len(candles) < minimum_bars:
            return Signal(SignalAction.HOLD, f"need at least {minimum_bars} candles")

        latest_index = len(candles) - 1
        factors = compute_factor_series(candles, self.strategy_config)
        latest_factors = factors.latest()
        if not latest_factors.is_ready():
            return Signal(SignalAction.HOLD, "indicators warming up")

        close_price = latest_factors.close
        fast_value = latest_factors.fast_ema
        slow_value = latest_factors.slow_ema
        rsi_value = latest_factors.rsi
        atr_value = latest_factors.atr
        breakout_high = latest_factors.breakout_high
        breakout_low = latest_factors.breakout_low
        assert fast_value is not None
        assert slow_value is not None
        assert rsi_value is not None
        assert atr_value is not None
        assert breakout_high is not None
        assert breakout_low is not None

        if open_position is not None:
            return self._exit_signal(open_position, close_price, fast_value, slow_value, rsi_value)

        if weekly_trade_count >= self.risk_config.max_weekly_trades:
            return Signal(SignalAction.HOLD, "weekly trade cap reached")

        if last_trade_index is not None:
            bars_since_trade = latest_index - last_trade_index
            if bars_since_trade < self.strategy_config.cooldown_bars:
                return Signal(SignalAction.HOLD, "cooldown active")

        trend_up = fast_value > slow_value and close_price > slow_value
        trend_down = fast_value < slow_value and close_price < slow_value
        stop_distance = self._bounded_stop_distance(close_price, atr_value)

        long_rsi_ok = self.strategy_config.long_min_rsi <= rsi_value <= self.strategy_config.long_max_rsi
        if trend_up and close_price > breakout_high and long_rsi_ok:
            return Signal(
                action=SignalAction.OPEN,
                side=Side.LONG,
                entry_price=close_price,
                stop_loss=close_price - stop_distance,
                take_profit=close_price + stop_distance * self._take_profit_ratio(),
                confidence=self._confidence(close_price, slow_value, rsi_value, Side.LONG),
                reason="long trend breakout",
            )

        short_rsi_ok = self.strategy_config.short_min_rsi <= rsi_value <= self.strategy_config.short_max_rsi
        if trend_down and close_price < breakout_low and short_rsi_ok:
            return Signal(
                action=SignalAction.OPEN,
                side=Side.SHORT,
                entry_price=close_price,
                stop_loss=close_price + stop_distance,
                take_profit=close_price - stop_distance * self._take_profit_ratio(),
                confidence=self._confidence(close_price, slow_value, rsi_value, Side.SHORT),
                reason="short trend breakdown",
            )

        return Signal(SignalAction.HOLD, "no breakout setup")

    def _exit_signal(self, position: Position, close_price: float, fast_ema: float, slow_ema: float, rsi_value: float) -> Signal:
        if position.side == Side.LONG:
            if close_price <= position.stop_loss:
                return Signal(SignalAction.CLOSE, "long stop hit", side=position.side)
            if close_price >= position.take_profit:
                return Signal(SignalAction.CLOSE, "long take profit hit", side=position.side)
            if fast_ema < slow_ema and close_price < fast_ema:
                return Signal(SignalAction.CLOSE, "long trend flip", side=position.side)
            if rsi_value >= self.strategy_config.long_exit_rsi:
                return Signal(SignalAction.CLOSE, "long RSI extension", side=position.side)
        else:
            if close_price >= position.stop_loss:
                return Signal(SignalAction.CLOSE, "short stop hit", side=position.side)
            if close_price <= position.take_profit:
                return Signal(SignalAction.CLOSE, "short take profit hit", side=position.side)
            if fast_ema > slow_ema and close_price > fast_ema:
                return Signal(SignalAction.CLOSE, "short trend flip", side=position.side)
            if rsi_value <= self.strategy_config.short_exit_rsi:
                return Signal(SignalAction.CLOSE, "short RSI extension", side=position.side)
        return Signal(SignalAction.HOLD, "position still valid", side=position.side)

    def _bounded_stop_distance(self, close_price: float, atr_value: float) -> float:
        atr_stop = atr_value * self.risk_config.stop_atr_multiple
        minimum_stop = close_price * self.risk_config.min_stop_pct
        maximum_stop = close_price * self.risk_config.max_stop_pct
        return min(max(atr_stop, minimum_stop), maximum_stop)

    def _take_profit_ratio(self) -> float:
        return self.risk_config.take_profit_atr_multiple / self.risk_config.stop_atr_multiple

    @staticmethod
    def _confidence(close_price: float, slow_ema: float, rsi_value: float, side: Side) -> float:
        trend_distance = abs(close_price - slow_ema) / close_price
        if side == Side.LONG:
            rsi_quality = max(0.0, 1.0 - abs(rsi_value - 58.0) / 28.0)
        else:
            rsi_quality = max(0.0, 1.0 - abs(rsi_value - 42.0) / 28.0)
        return min(1.0, 0.45 + trend_distance * 8 + rsi_quality * 0.35)
