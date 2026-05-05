from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import plotly.io as pio

from backtest.engine import BacktestEngine
from factors import FactorValue, build_factor_signals, compute_factor_series, default_factor_repository
from models import default_model_signal_model
from trading.config import AppConfig
from trading.data import DatasetMeta
from trading.domain import Candle
from trading.plotting import build_correlation_heatmap, build_mid_price_figure, build_signal_distribution_figure, build_signal_overlay_figure
from trading.signals import CorrelationResult, SignalSummary, future_returns, signal_forward_return_correlations, summarize_signals
from trading.strategy import SwingPerpsStrategy


DEFAULT_FORWARD_HORIZONS = [1, 2, 4, 8, 16]


def default_analysis_report_path(market: str) -> Path:
    return Path("reports") / f"{market.lower()}_analysis.html"


def write_analysis_report(
    candles: list[Candle],
    output_path: Path,
    *,
    config: AppConfig,
    data_path: Path,
    meta: DatasetMeta | None = None,
    horizons: list[int] | None = None,
    factor_names: list[str] | None = None,
) -> Path:
    if not candles:
        raise ValueError("cannot analyze an empty candle series")

    factor_series = compute_factor_series(candles, config.strategy)
    latest_factors = factor_series.latest()
    factor_repository = default_factor_repository()
    factor_values = factor_repository.latest_values(latest_factors)
    factor_signals = build_factor_signals(factor_series, repository=factor_repository, names=factor_names)
    model_output = default_model_signal_model().predict(candles, factor_series)
    research_signals = factor_signals + model_output.signals
    selected_horizons = horizons or DEFAULT_FORWARD_HORIZONS
    returns_by_horizon = future_returns(candles, selected_horizons)
    correlations = signal_forward_return_correlations(research_signals, returns_by_horizon)
    signal_summaries = summarize_signals(research_signals)
    backtest_result = BacktestEngine(config.strategy, config.risk).run(candles)
    signal = SwingPerpsStrategy(config.strategy, config.risk).analyze(candles)
    price_figure = build_mid_price_figure(
        candles,
        strategy_config=config.strategy,
        meta=meta,
        title=f"{config.strategy.market} Analysis",
    )
    signal_figure = build_signal_overlay_figure(
        candles,
        research_signals,
        title=f"{config.strategy.market} Normalized Factor and Model Signals",
    )
    distribution_figure = build_signal_distribution_figure(
        research_signals,
        title=f"{config.strategy.market} Signal Distribution",
    )
    correlation_figure = build_correlation_heatmap(
        correlations,
        title=f"{config.strategy.market} Signal vs Forward Return Correlation",
    )
    chart_html = pio.to_html(price_figure, include_plotlyjs="cdn", full_html=False)
    signal_chart_html = pio.to_html(signal_figure, include_plotlyjs=False, full_html=False)
    distribution_chart_html = pio.to_html(distribution_figure, include_plotlyjs=False, full_html=False)
    correlation_chart_html = pio.to_html(correlation_figure, include_plotlyjs=False, full_html=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_report_html(
            config=config,
            data_path=data_path,
            meta=meta,
            candles=candles,
            factor_values=factor_values,
            signal_summaries=signal_summaries,
            correlations=correlations,
            backtest_summary=backtest_result.summary(),
            signal_payload=signal.__dict__,
            model_name=model_output.model_name,
            chart_html=chart_html,
            signal_chart_html=signal_chart_html,
            distribution_chart_html=distribution_chart_html,
            correlation_chart_html=correlation_chart_html,
        ),
        encoding="utf-8",
    )
    return output_path


def _render_report_html(
    *,
    config: AppConfig,
    data_path: Path,
    meta: DatasetMeta | None,
    candles: list[Candle],
    factor_values: list[FactorValue],
    signal_summaries: list[SignalSummary],
    correlations: list[CorrelationResult],
    backtest_summary: dict[str, Any],
    signal_payload: dict[str, Any],
    model_name: str,
    chart_html: str,
    signal_chart_html: str,
    distribution_chart_html: str,
    correlation_chart_html: str,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    meta_rows = _meta_rows(meta, data_path, candles)
    cards = "".join(
        f"<div class='card'><span>{_escape(key)}</span><strong>{_escape(_format_value(value))}</strong></div>"
        for key, value in backtest_summary.items()
    )
    factor_rows = "".join(
        "<tr>"
        f"<td>{_escape(value.definition.group)}</td>"
        f"<td>{_escape(value.definition.label)}</td>"
        f"<td>{_escape(_format_value(value.value))}</td>"
        f"<td>{_escape(value.definition.description)}</td>"
        "</tr>"
        for value in factor_values
    )
    signal_json = _escape(json.dumps(signal_payload, indent=2, default=str))
    meta_table = "".join(f"<tr><th>{_escape(key)}</th><td>{_escape(value)}</td></tr>" for key, value in meta_rows)
    signal_summary_rows = _signal_summary_rows(signal_summaries)
    correlation_rows = _correlation_rows(correlations, config.strategy.candle_minutes)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(config.strategy.market)} Analysis Report</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; color: #111827; background: #f8fafc; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 24px 48px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .muted {{ color: #64748b; font-size: 13px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 18px 0; }}
    .card {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }}
    .card span {{ display: block; color: #64748b; font-size: 12px; text-transform: uppercase; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 20px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ width: 190px; color: #475569; background: #f1f5f9; }}
    .wide th {{ width: auto; }}
    tr:last-child th, tr:last-child td {{ border-bottom: 0; }}
    pre {{ background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 14px; overflow: auto; }}
    .chart {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px; }}
  </style>
</head>
<body>
<main>
  <h1>{_escape(config.strategy.market)} Analysis Report</h1>
  <div class="muted">Generated at {generated_at} from { _escape(str(data_path)) }</div>

  <section>
    <h2>Backtest Summary</h2>
    <div class="cards">{cards}</div>
  </section>

  <section>
    <h2>Market Data</h2>
    <table>{meta_table}</table>
  </section>

  <section>
    <h2>Latest Factor Snapshot</h2>
    <table>
      <tr><th>Group</th><th>Factor</th><th>Value</th><th>Description</th></tr>
      {factor_rows}
    </table>
  </section>

    <section>
        <h2>Research Signals</h2>
        <div class="muted">Factor signals and model outputs are normalized into a common signal scale. Model: {_escape(model_name)}.</div>
        <table class="wide">
            <tr><th>Source</th><th>Group</th><th>Signal</th><th>Latest</th><th>Mean</th><th>Stdev</th><th>Min</th><th>Max</th><th>Norm</th></tr>
            {signal_summary_rows}
        </table>
    </section>

    <section>
        <h2>Forward Return Correlation</h2>
        <table class="wide">
            <tr><th>Source</th><th>Signal</th><th>Horizon</th><th>Samples</th><th>Correlation</th></tr>
            {correlation_rows}
        </table>
    </section>

  <section>
    <h2>Latest Signal</h2>
    <pre>{signal_json}</pre>
  </section>

  <section>
    <h2>Chart</h2>
    <div class="chart">{chart_html}</div>
  </section>

    <section>
        <h2>Signal Overlay</h2>
        <div class="chart">{signal_chart_html}</div>
    </section>

    <section>
        <h2>Signal Distribution</h2>
        <div class="chart">{distribution_chart_html}</div>
    </section>

    <section>
        <h2>Correlation Heatmap</h2>
        <div class="chart">{correlation_chart_html}</div>
    </section>
</main>
</body>
</html>
"""


def parse_horizons(raw_value: str | None) -> list[int]:
    if raw_value is None or raw_value.strip() == "":
        return list(DEFAULT_FORWARD_HORIZONS)
    horizons: list[int] = []
    for part in raw_value.split(","):
        value = int(part.strip())
        if value <= 0:
            raise ValueError("correlation horizons must be positive")
        horizons.append(value)
    return horizons


def parse_factor_names(raw_value: str | None) -> list[str] | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _meta_rows(meta: DatasetMeta | None, data_path: Path, candles: list[Candle]) -> list[tuple[str, str]]:
    if meta is None:
        return [
            ("path", str(data_path)),
            ("schema", "unknown"),
            ("count", str(len(candles))),
            ("first_ts", candles[0].timestamp.isoformat()),
            ("last_ts", candles[-1].timestamp.isoformat()),
        ]
    payload = meta.to_json_dict()
    rows = [("path", str(data_path))]
    for key in ("schema", "symbol", "instrument", "venue", "interval_minutes", "source", "first_ts", "last_ts", "count", "notes"):
        rows.append((key, str(payload.get(key, ""))))
    rows.append(("extras", json.dumps(payload.get("extras", {}), sort_keys=True)))
    return rows


def _signal_summary_rows(summaries: list[SignalSummary]) -> str:
    return "".join(
        "<tr>"
        f"<td>{_escape(summary.source)}</td>"
        f"<td>{_escape(summary.group)}</td>"
        f"<td>{_escape(summary.label)}</td>"
        f"<td>{_escape(_format_value(summary.latest))}</td>"
        f"<td>{_escape(_format_value(summary.mean))}</td>"
        f"<td>{_escape(_format_value(summary.stdev))}</td>"
        f"<td>{_escape(_format_value(summary.minimum))}</td>"
        f"<td>{_escape(_format_value(summary.maximum))}</td>"
        f"<td>{_escape(summary.normalization)}</td>"
        "</tr>"
        for summary in summaries
    )


def _correlation_rows(correlations: list[CorrelationResult], candle_minutes: int) -> str:
    return "".join(
        "<tr>"
        f"<td>{_escape(result.signal_source)}</td>"
        f"<td>{_escape(result.signal_label)}</td>"
        f"<td>{_escape(_format_horizon(result.horizon, candle_minutes))}</td>"
        f"<td>{result.sample_size}</td>"
        f"<td>{_escape(_format_value(result.correlation))}</td>"
        "</tr>"
        for result in correlations
    )


def _format_horizon(horizon: int, candle_minutes: int) -> str:
    total_minutes = horizon * candle_minutes
    if total_minutes % (24 * 60) == 0:
        return f"+{horizon} ticks ({total_minutes // (24 * 60)}d)"
    if total_minutes % 60 == 0:
        return f"+{horizon} ticks ({total_minutes // 60}h)"
    return f"+{horizon} ticks ({total_minutes}m)"


def _format_value(value: Any) -> str:
    if value is None:
        return "warming"
    if isinstance(value, float):
        if value == float("inf"):
            return "Infinity"
        return f"{value:,.4f}"
    return str(value)


def _escape(value: str) -> str:
    return html.escape(value, quote=True)