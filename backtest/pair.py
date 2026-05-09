from __future__ import annotations

import html
import math
from bisect import insort
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from factors import compute_factor_series
from trading.config import RiskConfig, StrategyConfig
from trading.domain import Candle
from trading.risk import iso_week_key


@dataclass(frozen=True)
class PairBacktestConfig:
    primary_label: str
    reference_label: str
    candle_minutes: int
    entry_z: float = 2.0
    entry_tail_fraction: float = 0.0
    regression_lookback: int = 96
    exit_z: float = 0.25
    stop_z: float = 4.0
    min_corr: float = 0.75
    max_hold_ticks: int = 96
    cooldown_ticks: int = 10
    gross_exposure_usd: float = 2000.0
    fee_bps: float = 6.0
    hourly_cost_bps: float = 0.0
    max_weekly_trades: int = 10


@dataclass(frozen=True)
class PairTrade:
    opened_at: datetime
    closed_at: datetime
    direction: int
    primary_side: str
    reference_side: str
    entry_signal: float
    exit_signal: float | None
    beta: float
    corr: float
    primary_entry: float
    reference_entry: float
    primary_exit: float
    reference_exit: float
    primary_notional_usd: float
    reference_notional_usd: float
    gross_pnl_usd: float
    fees_usd: float
    carry_usd: float
    pnl_usd: float
    hold_ticks: int
    reason: str

    @property
    def gross_exposure_usd(self) -> float:
        return abs(self.primary_notional_usd) + abs(self.reference_notional_usd)


@dataclass(frozen=True)
class PairBacktestResult:
    config: PairBacktestConfig
    trades: list[PairTrade]
    starting_equity: float
    final_equity: float
    equity_curve: list[tuple[datetime, float]]
    timestamps: list[datetime]
    primary_closes: list[float]
    reference_closes: list[float | None]
    signals: list[float | None]
    betas: list[float | None]
    correlations: list[float | None]

    def summary(self) -> dict[str, float | int | str]:
        net_pnl = self.final_equity - self.starting_equity
        fees = sum(trade.fees_usd for trade in self.trades)
        carry = sum(trade.carry_usd for trade in self.trades)
        gross_pnl = sum(trade.gross_pnl_usd for trade in self.trades)
        wins = sum(1 for trade in self.trades if trade.pnl_usd > 0)
        average_hold_ticks = _mean([trade.hold_ticks for trade in self.trades])
        average_hold_hours = average_hold_ticks * self.config.candle_minutes / 60 if average_hold_ticks is not None else None
        return {
            "primary": self.config.primary_label,
            "reference": self.config.reference_label,
            "entry_mode": f"top_bottom_{self.config.entry_tail_fraction * 100:.2f}%" if self.config.entry_tail_fraction > 0 else f"abs_z_gte_{self.config.entry_z}",
            "regression_lookback": self.config.regression_lookback,
            "trades": len(self.trades),
            "final_equity": round(self.final_equity, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "return_pct": round(net_pnl / self.starting_equity * 100, 2) if self.starting_equity else 0.0,
            "gross_pnl_usd": round(gross_pnl, 2),
            "fees_usd": round(fees, 2),
            "carry_usd": round(carry, 2),
            "win_rate_pct": round(wins / len(self.trades) * 100, 2) if self.trades else 0.0,
            "profit_factor": round(_profit_factor(self.trades), 2),
            "max_drawdown_pct": round(_max_drawdown_pct(self.equity_curve), 2),
            "annualized_sharpe": round(_annualized_sharpe(self.equity_curve, self.config.candle_minutes), 2),
            "avg_hold_ticks": round(average_hold_ticks, 2) if average_hold_ticks is not None else 0.0,
            "avg_hold_hours": round(average_hold_hours, 2) if average_hold_hours is not None else 0.0,
        }


@dataclass
class _OpenPairPosition:
    entry_index: int
    opened_at: datetime
    direction: int
    entry_signal: float
    beta: float
    corr: float
    primary_entry: float
    reference_entry: float
    primary_signed_notional_usd: float
    reference_signed_notional_usd: float


class PairBacktestEngine:
    def __init__(self, strategy_config: StrategyConfig, risk_config: RiskConfig, pair_config: PairBacktestConfig) -> None:
        if pair_config.entry_tail_fraction < 0 or pair_config.entry_tail_fraction >= 0.5:
            raise ValueError("entry_tail_fraction must be non-negative and less than 0.5")
        self.strategy_config = strategy_config
        self.risk_config = risk_config
        self.pair_config = pair_config

    def run(self, primary_candles: list[Candle], reference_candles: list[Candle]) -> PairBacktestResult:
        if not primary_candles:
            raise ValueError("primary candle series is empty")
        if not reference_candles:
            raise ValueError("reference candle series is empty")

        reference_by_timestamp = {candle.timestamp: candle for candle in reference_candles}
        factors = compute_factor_series(
            primary_candles,
            self.strategy_config,
            reference_candles=reference_candles,
            cross_asset_lookback=self.pair_config.regression_lookback,
        )
        signals = factors.cross_asset_reversion
        betas = factors.cross_asset_beta
        correlations = factors.cross_asset_corr
        entry_directions = _entry_directions(
            signals,
            self.pair_config.entry_z,
            self.pair_config.entry_tail_fraction,
        )
        reference_closes = [
            reference_by_timestamp[candle.timestamp].close if candle.timestamp in reference_by_timestamp else None
            for candle in primary_candles
        ]

        realized_equity = self.risk_config.equity_usd
        equity_curve: list[tuple[datetime, float]] = []
        trades: list[PairTrade] = []
        open_position: _OpenPairPosition | None = None
        weekly_open_counts: dict[tuple[int, int], int] = {}
        last_exit_index: int | None = None

        for signal_index in range(len(primary_candles) - 1):
            self._append_equity_point(
                equity_curve,
                primary_candles[signal_index],
                reference_by_timestamp,
                realized_equity,
                open_position,
            )

            execution_index = signal_index + 1
            if open_position is not None:
                exit_reason = self._exit_reason(open_position, signals[signal_index], execution_index)
                if exit_reason is not None:
                    trade = self._close_position(
                        open_position,
                        primary_candles,
                        reference_by_timestamp,
                        signals[signal_index],
                        execution_index,
                        exit_reason,
                    )
                    if trade is not None:
                        trades.append(trade)
                        realized_equity += trade.pnl_usd
                        open_position = None
                        last_exit_index = execution_index
                    continue

            if open_position is None:
                open_position = self._maybe_open_position(
                    primary_candles,
                    reference_by_timestamp,
                    signals,
                    entry_directions,
                    betas,
                    correlations,
                    weekly_open_counts,
                    last_exit_index,
                    signal_index,
                    execution_index,
                )

        if open_position is not None:
            trade = self._close_position(
                open_position,
                primary_candles,
                reference_by_timestamp,
                signals[-1],
                len(primary_candles) - 1,
                "end_of_sample",
            )
            if trade is not None:
                trades.append(trade)
                realized_equity += trade.pnl_usd

        self._append_equity_point(
            equity_curve,
            primary_candles[-1],
            reference_by_timestamp,
            realized_equity,
            None,
        )

        return PairBacktestResult(
            config=self.pair_config,
            trades=trades,
            starting_equity=self.risk_config.equity_usd,
            final_equity=realized_equity,
            equity_curve=equity_curve,
            timestamps=[candle.timestamp for candle in primary_candles],
            primary_closes=[candle.close for candle in primary_candles],
            reference_closes=reference_closes,
            signals=signals,
            betas=betas,
            correlations=correlations,
        )

    def _maybe_open_position(
        self,
        primary_candles: list[Candle],
        reference_by_timestamp: dict[datetime, Candle],
        signals: list[float | None],
        entry_directions: list[int | None],
        betas: list[float | None],
        correlations: list[float | None],
        weekly_open_counts: dict[tuple[int, int], int],
        last_exit_index: int | None,
        signal_index: int,
        execution_index: int,
    ) -> _OpenPairPosition | None:
        signal = signals[signal_index]
        beta = betas[signal_index]
        corr = correlations[signal_index]
        direction = entry_directions[signal_index]
        if direction is None or signal is None or beta is None or corr is None:
            return None
        if abs(beta) < 1e-9:
            return None
        if corr < self.pair_config.min_corr:
            return None
        if last_exit_index is not None and execution_index - last_exit_index < self.pair_config.cooldown_ticks:
            return None

        entry_candle = primary_candles[execution_index]
        reference_entry = reference_by_timestamp.get(entry_candle.timestamp)
        if reference_entry is None:
            return None

        weekly_key = iso_week_key(entry_candle.timestamp)
        weekly_count = weekly_open_counts.get(weekly_key, 0)
        if self.pair_config.max_weekly_trades > 0 and weekly_count >= self.pair_config.max_weekly_trades:
            return None

        primary_signed_notional, reference_signed_notional = _signed_pair_notionals(
            direction,
            beta,
            self.pair_config.gross_exposure_usd,
        )
        weekly_open_counts[weekly_key] = weekly_count + 1
        return _OpenPairPosition(
            entry_index=execution_index,
            opened_at=entry_candle.timestamp,
            direction=direction,
            entry_signal=signal,
            beta=beta,
            corr=corr,
            primary_entry=entry_candle.close,
            reference_entry=reference_entry.close,
            primary_signed_notional_usd=primary_signed_notional,
            reference_signed_notional_usd=reference_signed_notional,
        )

    def _exit_reason(self, position: _OpenPairPosition, signal: float | None, execution_index: int) -> str | None:
        if signal is not None:
            if abs(signal) <= self.pair_config.exit_z:
                return "mean_reversion"
            directional_signal = position.direction * signal
            if directional_signal < 0:
                return "signal_flip"
            if self.pair_config.stop_z > 0 and directional_signal >= self.pair_config.stop_z:
                return "stop_z"
        if self.pair_config.max_hold_ticks > 0 and execution_index - position.entry_index >= self.pair_config.max_hold_ticks:
            return "max_hold"
        return None

    def _close_position(
        self,
        position: _OpenPairPosition,
        primary_candles: list[Candle],
        reference_by_timestamp: dict[datetime, Candle],
        exit_signal: float | None,
        execution_index: int,
        reason: str,
    ) -> PairTrade | None:
        exit_candle = primary_candles[execution_index]
        reference_exit = reference_by_timestamp.get(exit_candle.timestamp)
        if reference_exit is None:
            return None
        primary_return = exit_candle.close / position.primary_entry - 1
        reference_return = reference_exit.close / position.reference_entry - 1
        gross_pnl = position.primary_signed_notional_usd * primary_return + position.reference_signed_notional_usd * reference_return
        gross_exposure = abs(position.primary_signed_notional_usd) + abs(position.reference_signed_notional_usd)
        fees = gross_exposure * 2 * self.pair_config.fee_bps / 10000
        hold_ticks = execution_index - position.entry_index
        hold_hours = hold_ticks * self.pair_config.candle_minutes / 60
        carry = gross_exposure * self.pair_config.hourly_cost_bps / 10000 * hold_hours
        pnl = gross_pnl - fees - carry
        return PairTrade(
            opened_at=position.opened_at,
            closed_at=exit_candle.timestamp,
            direction=position.direction,
            primary_side=_side_label(position.primary_signed_notional_usd),
            reference_side=_side_label(position.reference_signed_notional_usd),
            entry_signal=position.entry_signal,
            exit_signal=exit_signal,
            beta=position.beta,
            corr=position.corr,
            primary_entry=position.primary_entry,
            reference_entry=position.reference_entry,
            primary_exit=exit_candle.close,
            reference_exit=reference_exit.close,
            primary_notional_usd=position.primary_signed_notional_usd,
            reference_notional_usd=position.reference_signed_notional_usd,
            gross_pnl_usd=gross_pnl,
            fees_usd=fees,
            carry_usd=carry,
            pnl_usd=pnl,
            hold_ticks=hold_ticks,
            reason=reason,
        )

    def _append_equity_point(
        self,
        equity_curve: list[tuple[datetime, float]],
        candle: Candle,
        reference_by_timestamp: dict[datetime, Candle],
        realized_equity: float,
        position: _OpenPairPosition | None,
    ) -> None:
        equity = realized_equity
        if position is not None:
            reference_candle = reference_by_timestamp.get(candle.timestamp)
            if reference_candle is not None:
                primary_return = candle.close / position.primary_entry - 1
                reference_return = reference_candle.close / position.reference_entry - 1
                equity += position.primary_signed_notional_usd * primary_return + position.reference_signed_notional_usd * reference_return
        equity_curve.append((candle.timestamp, equity))


def default_pair_backtest_report_path(primary_label: str, reference_label: str, candle_minutes: int) -> Path:
    primary_slug = _slugify(primary_label)
    reference_slug = _slugify(reference_label)
    return Path("reports") / "pair_backtests" / f"{primary_slug}_{reference_slug}_{candle_minutes}m_pair_backtest.html"


def write_pair_backtest_report(result: PairBacktestResult, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure_html = pio.to_html(_build_pair_backtest_figure(result), include_plotlyjs="cdn", full_html=False)
    summary_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in result.summary().items()
    )
    trade_rows = "".join(_trade_row(trade) for trade in result.trades[-80:])
    content = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>{html.escape(result.config.primary_label)}-{html.escape(result.config.reference_label)} Pair Backtest</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #111827; background: #f8fafc; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{ margin: 18px 0; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 7px 9px; font-size: 13px; text-align: right; }}
    th {{ background: #f1f5f9; text-align: left; }}
    .muted {{ color: #64748b; font-size: 13px; margin-bottom: 12px; }}
    .wrap {{ overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>{html.escape(result.config.primary_label)} / {html.escape(result.config.reference_label)} Pair Backtest</h1>
    <div class=\"muted\">Signal: rolling log-price residual z-score. Positive signal opens long {html.escape(result.config.primary_label)} / short hedge {html.escape(result.config.reference_label)}; negative signal opens the opposite. Entries execute on the next candle close. Entry mode: {_entry_mode_text(result.config)}.</div>
  <section>
    <h2>Summary</h2>
    <table>{summary_rows}</table>
  </section>
  <section>{figure_html}</section>
  <section>
    <h2>Recent Trades</h2>
    <div class=\"muted\">Showing the latest 80 closed pair trades.</div>
    <div class=\"wrap\">
      <table>
        <tr><th>Opened</th><th>Closed</th><th>Primary</th><th>Reference</th><th>Entry Signal</th><th>Exit Signal</th><th>Beta</th><th>Corr</th><th>Hold</th><th>Gross PnL</th><th>Fees</th><th>Carry</th><th>Net PnL</th><th>Reason</th></tr>
        {trade_rows}
      </table>
    </div>
  </section>
</body>
</html>"""
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _build_pair_backtest_figure(result: PairBacktestResult) -> go.Figure:
    figure = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.28, 0.26, 0.28, 0.18],
        vertical_spacing=0.05,
        subplot_titles=("Equity", "Normalized Prices", "Pair Reversion Signal", "Rolling Return Correlation"),
    )
    equity_timestamps = [item[0] for item in result.equity_curve]
    equity_values = [item[1] for item in result.equity_curve]
    figure.add_trace(
        go.Scatter(x=equity_timestamps, y=equity_values, mode="lines", name="Equity", line={"color": "#111827", "width": 1.7}),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=result.timestamps, y=_normalize_to_100(result.primary_closes), mode="lines", name=result.config.primary_label, line={"color": "#2563eb", "width": 1.1}),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=result.timestamps, y=_normalize_to_100(result.reference_closes), mode="lines", name=result.config.reference_label, line={"color": "#dc2626", "width": 1.1}),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=result.timestamps, y=result.signals, mode="lines", name="Reversion Signal", line={"color": "#7c3aed", "width": 1.2}),
        row=3,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=result.timestamps, y=result.correlations, mode="lines", name="Rolling Corr", line={"color": "#0f766e", "width": 1.1}),
        row=4,
        col=1,
    )
    entry_times = [trade.opened_at for trade in result.trades]
    entry_signals = [trade.entry_signal for trade in result.trades]
    exit_times = [trade.closed_at for trade in result.trades]
    exit_signals = [trade.exit_signal for trade in result.trades]
    figure.add_trace(
        go.Scatter(x=entry_times, y=entry_signals, mode="markers", name="Entries", marker={"color": "#16a34a", "size": 7, "symbol": "triangle-up"}),
        row=3,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=exit_times, y=exit_signals, mode="markers", name="Exits", marker={"color": "#f97316", "size": 7, "symbol": "x"}),
        row=3,
        col=1,
    )
    if result.config.entry_tail_fraction <= 0:
        for threshold in (result.config.entry_z, -result.config.entry_z):
            figure.add_hline(y=threshold, line_dash="dot", line_color="#94a3b8", row=3, col=1)
    for threshold in (result.config.exit_z, -result.config.exit_z):
        figure.add_hline(y=threshold, line_dash="dot", line_color="#94a3b8", row=3, col=1)
    figure.add_hline(y=result.config.min_corr, line_dash="dot", line_color="#94a3b8", row=4, col=1)
    figure.update_layout(
        template="plotly_white",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        height=980,
        margin={"l": 58, "r": 24, "t": 78, "b": 42},
    )
    figure.update_yaxes(title_text="USD", row=1, col=1)
    figure.update_yaxes(title_text="Index", row=2, col=1)
    figure.update_yaxes(title_text="Z", row=3, col=1)
    figure.update_yaxes(title_text="Corr", row=4, col=1)
    return figure


def _trade_row(trade: PairTrade) -> str:
    return (
        "<tr>"
        f"<td>{_format_time(trade.opened_at)}</td>"
        f"<td>{_format_time(trade.closed_at)}</td>"
        f"<td>{html.escape(trade.primary_side)}</td>"
        f"<td>{html.escape(trade.reference_side)}</td>"
        f"<td>{trade.entry_signal:.4f}</td>"
        f"<td>{'' if trade.exit_signal is None else f'{trade.exit_signal:.4f}'}</td>"
        f"<td>{trade.beta:.4f}</td>"
        f"<td>{trade.corr:.4f}</td>"
        f"<td>{trade.hold_ticks}</td>"
        f"<td>{trade.gross_pnl_usd:.2f}</td>"
        f"<td>{trade.fees_usd:.2f}</td>"
        f"<td>{trade.carry_usd:.2f}</td>"
        f"<td>{trade.pnl_usd:.2f}</td>"
        f"<td>{html.escape(trade.reason)}</td>"
        "</tr>"
    )


def _entry_directions(signals: list[float | None], entry_z: float, entry_tail_fraction: float) -> list[int | None]:
    if entry_tail_fraction <= 0:
        return [_fixed_entry_direction(signal, entry_z) for signal in signals]

    historical_values: list[float] = []
    directions: list[int | None] = []
    min_samples = max(100, math.ceil(1 / entry_tail_fraction))
    for signal in signals:
        direction = None
        if signal is not None and len(historical_values) >= min_samples:
            bucket_size = max(1, int(len(historical_values) * entry_tail_fraction))
            lower_threshold = historical_values[bucket_size - 1]
            upper_threshold = historical_values[-bucket_size]
            if signal <= lower_threshold:
                direction = -1
            elif signal >= upper_threshold:
                direction = 1
        directions.append(direction)
        if signal is not None:
            insort(historical_values, signal)
    return directions


def _fixed_entry_direction(signal: float | None, entry_z: float) -> int | None:
    if signal is None or abs(signal) < entry_z:
        return None
    return 1 if signal > 0 else -1


def _entry_mode_text(config: PairBacktestConfig) -> str:
    if config.entry_tail_fraction > 0:
        return f"top/bottom {config.entry_tail_fraction * 100:.2f}% of live historical signals"
    return f"abs(signal) >= {config.entry_z:.4f}"


def _signed_pair_notionals(direction: int, beta: float, gross_exposure_usd: float) -> tuple[float, float]:
    beta_abs = abs(beta)
    primary_notional = gross_exposure_usd / (1 + beta_abs)
    reference_notional = gross_exposure_usd - primary_notional
    primary_signed = direction * primary_notional
    reference_signed = -direction * math.copysign(reference_notional, beta)
    return primary_signed, reference_signed


def _side_label(signed_notional: float) -> str:
    return "long" if signed_notional > 0 else "short"


def _profit_factor(trades: list[PairTrade]) -> float:
    gross_profit = sum(trade.pnl_usd for trade in trades if trade.pnl_usd > 0)
    gross_loss = abs(sum(trade.pnl_usd for trade in trades if trade.pnl_usd < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _max_drawdown_pct(equity_curve: list[tuple[datetime, float]]) -> float:
    peak = None
    max_drawdown = 0.0
    for _, equity in equity_curve:
        peak = equity if peak is None else max(peak, equity)
        if peak and peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    return max_drawdown


def _annualized_sharpe(equity_curve: list[tuple[datetime, float]], candle_minutes: int) -> float:
    returns: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        previous_equity = previous[1]
        current_equity = current[1]
        if previous_equity > 0:
            returns.append(current_equity / previous_equity - 1)
    if len(returns) < 2:
        return 0.0
    average_return = sum(returns) / len(returns)
    variance = sum((value - average_return) ** 2 for value in returns) / (len(returns) - 1)
    stdev = math.sqrt(variance)
    if stdev == 0:
        return 0.0
    periods_per_year = 365 * 24 * 60 / candle_minutes
    return average_return / stdev * math.sqrt(periods_per_year)


def _mean(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _normalize_to_100(values: list[float | None]) -> list[float | None]:
    base = next((value for value in values if value is not None and value > 0), None)
    if base is None:
        return [None for _ in values]
    return [None if value is None else value / base * 100 for value in values]


def _format_time(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")