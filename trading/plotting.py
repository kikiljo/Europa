from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading.config import StrategyConfig
from trading.data import DatasetMeta, load_dataset_meta
from trading.domain import Candle
from trading.indicators import exponential_moving_average
from trading.signals import CorrelationResult, ResearchSignal


def default_plot_path(market: str) -> Path:
    return Path("reports") / f"{market.lower()}_mid_price.html"


def build_mid_price_figure(
    candles: list[Candle],
    *,
    strategy_config: StrategyConfig,
    meta: DatasetMeta | None = None,
    include_candles: bool = True,
    include_ema: bool = True,
    title: str | None = None,
) -> Path:
    if not candles:
        raise ValueError("cannot plot an empty candle series")

    timestamps = [candle.timestamp for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    mids = [(candle.high + candle.low) / 2 for candle in candles]
    closes = [candle.close for candle in candles]

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.78, 0.22],
        vertical_spacing=0.04,
        subplot_titles=("Price", "Range Width"),
    )

    if include_candles:
        figure.add_trace(
            go.Candlestick(
                x=timestamps,
                open=[candle.open for candle in candles],
                high=highs,
                low=lows,
                close=closes,
                name="OHLC",
                increasing_line_color="#138a63",
                decreasing_line_color="#c2410c",
                opacity=0.58,
            ),
            row=1,
            col=1,
        )

    figure.add_trace(
        go.Scatter(
            x=timestamps,
            y=mids,
            mode="lines",
            name="Mid (H+L)/2",
            line={"color": "#2563eb", "width": 1.7},
            hovertemplate="%{x}<br>mid=%{y:.4f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    if include_ema:
        for period, color in (
            (strategy_config.fast_ema_period, "#7c3aed"),
            (strategy_config.slow_ema_period, "#0f766e"),
        ):
            ema = exponential_moving_average(mids, period)
            figure.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=ema,
                    mode="lines",
                    name=f"EMA {period} on mid",
                    line={"color": color, "width": 1.1},
                    hovertemplate=f"%{{x}}<br>EMA {period}=%{{y:.4f}}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    figure.add_trace(
        go.Bar(
            x=timestamps,
            y=[high - low for high, low in zip(highs, lows)],
            name="High-Low Range",
            marker={"color": "#94a3b8"},
            hovertemplate="%{x}<br>range=%{y:.4f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    source = meta.source if meta else "canonical-csv"
    interval = meta.interval_minutes if meta else strategy_config.candle_minutes
    chart_title = title or f"{strategy_config.market} Mid Price ({interval}m, {source})"
    figure.update_layout(
        title={"text": chart_title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 56, "r": 24, "t": 76, "b": 48},
        height=760,
        xaxis_rangeslider_visible=False,
    )
    figure.update_yaxes(title_text="Price", row=1, col=1)
    figure.update_yaxes(title_text="Range", row=2, col=1)
    figure.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor")

    return figure


def write_mid_price_chart(
    candles: list[Candle],
    output_path: Path,
    *,
    strategy_config: StrategyConfig,
    meta: DatasetMeta | None = None,
    include_candles: bool = True,
    include_ema: bool = True,
    title: str | None = None,
) -> Path:
    figure = build_mid_price_figure(
        candles,
        strategy_config=strategy_config,
        meta=meta,
        include_candles=include_candles,
        include_ema=include_ema,
        title=title,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn", full_html=True)
    return output_path


def build_signal_overlay_figure(candles: list[Candle], signals: list[ResearchSignal], *, title: str) -> go.Figure:
    if not candles:
        raise ValueError("cannot plot signals for an empty candle series")
    timestamps = [candle.timestamp for candle in candles]
    mids = [(candle.high + candle.low) / 2 for candle in candles]

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.62, 0.38],
        vertical_spacing=0.05,
        subplot_titles=("Mid Price", "Normalized Signals"),
    )
    figure.add_trace(
        go.Scatter(
            x=timestamps,
            y=mids,
            mode="lines",
            name="Mid (H+L)/2",
            line={"color": "#111827", "width": 1.4},
            hovertemplate="%{x}<br>mid=%{y:.4f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    for signal in signals:
        figure.add_trace(
            go.Scatter(
                x=timestamps,
                y=signal.values,
                mode="lines",
                name=f"{signal.source}: {signal.label}",
                line={"width": 1.1},
                hovertemplate="%{x}<br>%{y:.4f}<extra></extra>",
            ),
            row=2,
            col=1,
        )
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 56, "r": 24, "t": 76, "b": 48},
        height=720,
    )
    figure.update_yaxes(title_text="Price", row=1, col=1)
    figure.update_yaxes(title_text="Signal", zeroline=True, zerolinecolor="#94a3b8", row=2, col=1)
    return figure


def build_signal_distribution_figure(signals: list[ResearchSignal], *, title: str) -> go.Figure:
    figure = go.Figure()
    for signal in signals:
        values = [value for value in signal.values if value is not None]
        if not values:
            continue
        figure.add_trace(
            go.Histogram(
                x=values,
                name=f"{signal.source}: {signal.label}",
                opacity=0.62,
                nbinsx=44,
                hovertemplate="signal=%{x:.4f}<br>count=%{y}<extra></extra>",
            )
        )
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        barmode="overlay",
        xaxis_title="Normalized Signal Value",
        yaxis_title="Observations",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 56, "r": 24, "t": 76, "b": 48},
        height=520,
    )
    return figure


def build_correlation_heatmap(results: list[CorrelationResult], *, title: str) -> go.Figure:
    labels = _unique_ordered([result.signal_label for result in results])
    horizons = _unique_ordered([result.horizon for result in results])
    by_key = {(result.signal_label, result.horizon): result.correlation for result in results}
    matrix = [[by_key.get((label, horizon)) for horizon in horizons] for label in labels]
    figure = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=[f"+{horizon}" for horizon in horizons],
            y=labels,
            zmin=-1,
            zmax=1,
            colorscale="RdBu",
            reversescale=True,
            colorbar={"title": "corr"},
            hovertemplate="signal=%{y}<br>horizon=%{x}<br>corr=%{z:.4f}<extra></extra>",
        )
    )
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        xaxis_title="Forward Sampling Ticks",
        yaxis_title="Signal",
        margin={"l": 128, "r": 24, "t": 76, "b": 48},
        height=max(430, 82 + len(labels) * 34),
    )
    return figure


def _unique_ordered(values: list) -> list:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def load_meta_for_chart(data_path: Path) -> DatasetMeta | None:
    return load_dataset_meta(data_path)