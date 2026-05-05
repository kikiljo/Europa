from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading.config import StrategyConfig
from trading.data import DatasetMeta, load_dataset_meta
from trading.indicators import exponential_moving_average
from trading.models import Candle


def default_plot_path(market: str) -> Path:
    return Path("reports") / f"{market.lower()}_mid_price.html"


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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn", full_html=True)
    return output_path


def load_meta_for_chart(data_path: Path) -> DatasetMeta | None:
    return load_dataset_meta(data_path)