from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import plotly.io as pio

from factors import DEFAULT_FACTOR_SIGNAL_NAMES, FactorValue, build_factor_signals, compute_factor_series, default_factor_repository
from trading.config import AppConfig
from trading.data import DatasetMeta
from trading.domain import Candle
from trading.plotting import build_mid_price_figure, build_signal_decay_figure, build_signal_distribution_figure, build_tail_event_price_figure
from trading.signals import (
    CorrelationResult,
    SignalSummary,
    TailEventSummary,
    future_price_changes,
    signal_forward_return_correlations,
    signal_forward_value_decile_comparisons,
    signal_tail_events,
    summarize_signals,
)


DEFAULT_FORWARD_HORIZONS = list(range(1, 241))
DEFAULT_REPORT_HORIZON_CHECKPOINTS = [1, 2, 4, 8, 16, 32, 48, 96, 144, 240]


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
    round_trip_cost_bps: float | None = None,
    hourly_cost_bps: float = 0.0,
    tail_fraction: float = 0.01,
    tail_lookback_ticks: int = 48,
    candle_minutes: int | None = None,
) -> Path:
    if not candles:
        raise ValueError("cannot analyze an empty candle series")

    factor_series = compute_factor_series(candles, config.strategy)
    latest_factors = factor_series.latest()
    factor_repository = default_factor_repository()
    selected_factor_names = _selected_factor_names(factor_names)
    known_factor_names = {definition.name for definition in factor_repository.definitions()}
    unknown_factor_names = [name for name in selected_factor_names if name not in known_factor_names]
    if unknown_factor_names:
        known = ", ".join(sorted(known_factor_names))
        unknown = ", ".join(unknown_factor_names)
        raise ValueError(f"unknown factor signal(s): {unknown}; available factors: {known}")

    values_by_name = {value.definition.name: value for value in factor_repository.latest_values(latest_factors)}
    factor_values = [values_by_name[name] for name in selected_factor_names]
    research_signals = build_factor_signals(factor_series, repository=factor_repository, names=selected_factor_names)
    selected_horizons = horizons or DEFAULT_FORWARD_HORIZONS
    analysis_candle_minutes = candle_minutes or (meta.interval_minutes if meta is not None else config.strategy.candle_minutes)
    price_changes_by_horizon = future_price_changes(candles, selected_horizons)
    correlations = signal_forward_return_correlations(research_signals, price_changes_by_horizon)
    decile_comparisons = signal_forward_value_decile_comparisons(research_signals, price_changes_by_horizon)
    tail_summary_horizons = _checkpoint_horizons(selected_horizons)
    tail_summary_price_changes = {horizon: price_changes_by_horizon[horizon] for horizon in tail_summary_horizons}
    tail_summaries, tail_points = signal_tail_events(
        research_signals,
        candles,
        tail_summary_price_changes,
        tail_fraction=tail_fraction,
        lookback_ticks=tail_lookback_ticks,
    )
    signal_summaries = summarize_signals(research_signals)
    selected_round_trip_cost_bps = config.risk.fee_bps * 2 if round_trip_cost_bps is None else round_trip_cost_bps
    cost_bps_by_horizon = _cost_bps_by_horizon(
        selected_horizons,
        candle_minutes=analysis_candle_minutes,
        round_trip_cost_bps=selected_round_trip_cost_bps,
        hourly_cost_bps=hourly_cost_bps,
    )
    cost_price_by_horizon = _cost_price_by_horizon(candles, cost_bps_by_horizon)
    price_figure = build_mid_price_figure(
        candles,
        strategy_config=config.strategy,
        meta=meta,
        title=f"{config.strategy.market} Mid Price Context",
    )
    decay_figure = build_signal_decay_figure(
        correlations,
        decile_comparisons,
        cost_price_by_horizon=cost_price_by_horizon,
        candle_minutes=analysis_candle_minutes,
        title=f"{config.strategy.market} Factor Signal Decay",
    )
    distribution_figure = build_signal_distribution_figure(
        research_signals,
        title=f"{config.strategy.market} Signal Distribution",
    )
    tail_event_figure = build_tail_event_price_figure(
        candles,
        tail_points,
        title=f"{config.strategy.market} Top and Bottom {tail_fraction * 100:.2f}% Signal Events",
    )
    decay_chart_html = pio.to_html(decay_figure, include_plotlyjs="cdn", full_html=False)
    distribution_chart_html = pio.to_html(distribution_figure, include_plotlyjs=False, full_html=False)
    tail_event_chart_html = pio.to_html(tail_event_figure, include_plotlyjs=False, full_html=False)
    price_chart_html = pio.to_html(price_figure, include_plotlyjs=False, full_html=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _render_report_html(
            config=config,
            data_path=data_path,
            meta=meta,
            candles=candles,
            selected_factor_names=selected_factor_names,
            factor_values=factor_values,
            signal_summaries=signal_summaries,
            correlations=correlations,
            tail_summaries=tail_summaries,
            tail_summary_horizons=tail_summary_horizons,
            candle_minutes=analysis_candle_minutes,
            cost_price_by_horizon=cost_price_by_horizon,
            round_trip_cost_bps=selected_round_trip_cost_bps,
            hourly_cost_bps=hourly_cost_bps,
            tail_fraction=tail_fraction,
            tail_lookback_ticks=tail_lookback_ticks,
            decay_chart_html=decay_chart_html,
            distribution_chart_html=distribution_chart_html,
            tail_event_chart_html=tail_event_chart_html,
            price_chart_html=price_chart_html,
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
    selected_factor_names: list[str],
    factor_values: list[FactorValue],
    signal_summaries: list[SignalSummary],
    correlations: list[CorrelationResult],
    tail_summaries: list[TailEventSummary],
    tail_summary_horizons: list[int],
    candle_minutes: int,
    cost_price_by_horizon: dict[int, float],
    round_trip_cost_bps: float,
    hourly_cost_bps: float,
    tail_fraction: float,
    tail_lookback_ticks: int,
    decay_chart_html: str,
    distribution_chart_html: str,
    tail_event_chart_html: str,
    price_chart_html: str,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    meta_rows = _meta_rows(meta, data_path, candles)
    horizons = _unique_ordered([result.horizon for result in correlations])
    horizon_label = _horizon_range_label(horizons, candle_minutes)
    cards = _setup_cards(
        signal_count=len(signal_summaries),
        factor_count=len(selected_factor_names),
        horizon_label=horizon_label,
        round_trip_cost_price=cost_price_by_horizon.get(1),
        max_cost_price=max(cost_price_by_horizon.values()) if cost_price_by_horizon else None,
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
    meta_table = "".join(f"<tr><th>{_escape(key)}</th><td>{_escape(value)}</td></tr>" for key, value in meta_rows)
    signal_summary_rows = _signal_summary_rows(signal_summaries)
    tail_summary_rows = _tail_summary_rows(tail_summaries, tail_summary_horizons, candle_minutes)
    selected_factor_text = ", ".join(selected_factor_names)
    cost_text = _cost_formula_text(round_trip_cost_bps, hourly_cost_bps, candle_minutes)
    tail_text = (
        f"Tail events use top and bottom {tail_fraction * 100:.2f}% normalized signal values. "
        f"Forward columns are signal-aligned: positive signal keeps the price move, negative signal flips it. "
        f"Lookback move uses raw price change over {tail_lookback_ticks} ticks."
    )

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{_escape(config.strategy.market)} Signal Analysis Report</title>
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
    <h1>{_escape(config.strategy.market)} Signal Analysis Report</h1>
  <div class="muted">Generated at {generated_at} from { _escape(str(data_path)) }</div>

  <section>
    <h2>Analysis Setup</h2>
    <div class="cards">{cards}</div>
        <div class="muted">Selected factors: {_escape(selected_factor_text)}. Cost curve is converted into price units: {_escape(cost_text)}.</div>
  </section>

  <section>
    <h2>Market Data</h2>
    <table>{meta_table}</table>
  </section>

  <section>
    <h2>Selected Factor Snapshot</h2>
    <table>
      <tr><th>Group</th><th>Factor</th><th>Value</th><th>Description</th></tr>
      {factor_rows}
    </table>
  </section>

    <section>
        <h2>Research Signals</h2>
        <div class="muted">Last Score is the latest normalized value in this dataset. Positive is evaluated as up/long, negative as down/short. Normalization uses expanding z-score from prior observations only.</div>
        <table class="wide">
            <tr><th>Source</th><th>Group</th><th>Signal</th><th>Last Score</th><th>Mean</th><th>Stdev</th><th>Min</th><th>Max</th><th>Norm</th></tr>
            {signal_summary_rows}
        </table>
    </section>

    <section>
        <h2>Signal Decay</h2>
        <div class="chart">{decay_chart_html}</div>
    </section>

    <section>
        <h2>Signal-Direction Tail Events</h2>
        <div class="muted">{_escape(tail_text)}</div>
        <table class="wide">
            {tail_summary_rows}
        </table>
    </section>

    <section>
        <h2>Tail Event Price Map</h2>
        <div class="chart">{tail_event_chart_html}</div>
    </section>

    <section>
        <h2>Signal Distribution</h2>
        <div class="chart">{distribution_chart_html}</div>
    </section>

    <section>
        <h2>Price Context</h2>
        <div class="chart">{price_chart_html}</div>
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
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_raw, end_raw = token.split("-", 1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
            if start <= 0 or end <= 0 or end < start:
                raise ValueError("correlation horizon ranges must be positive and increasing")
            horizons.extend(range(start, end + 1))
            continue
        value = int(token)
        if value <= 0:
            raise ValueError("correlation horizons must be positive")
        horizons.append(value)
    return _unique_ordered(horizons)


def parse_factor_names(raw_value: str | None) -> list[str] | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return _unique_ordered([part.strip() for part in raw_value.split(",") if part.strip()])


def _selected_factor_names(factor_names: list[str] | None) -> list[str]:
    return _unique_ordered(factor_names or list(DEFAULT_FACTOR_SIGNAL_NAMES))


def _setup_cards(
    *,
    signal_count: int,
    factor_count: int,
    horizon_label: str,
    round_trip_cost_price: float | None,
    max_cost_price: float | None,
) -> str:
    values = [
        ("signals", str(signal_count)),
        ("factors", str(factor_count)),
        ("horizons", horizon_label),
        ("round_trip_cost", _format_price_delta(round_trip_cost_price)),
        ("max_cost", _format_price_delta(max_cost_price)),
    ]
    return "".join(
        f"<div class='card'><span>{_escape(key)}</span><strong>{_escape(value)}</strong></div>"
        for key, value in values
    )


def _cost_bps_by_horizon(
    horizons: list[int],
    *,
    candle_minutes: int,
    round_trip_cost_bps: float,
    hourly_cost_bps: float,
) -> dict[int, float]:
    return {
        horizon: round_trip_cost_bps + hourly_cost_bps * (horizon * candle_minutes / 60)
        for horizon in horizons
    }


def _cost_formula_text(round_trip_cost_bps: float, hourly_cost_bps: float, candle_minutes: int) -> str:
    return (
        f"configured fee rates are multiplied by each horizon's mean sample close; "
        f"{candle_minutes} minutes per tick"
    )


def _cost_price_by_horizon(candles: list[Candle], cost_bps_by_horizon: dict[int, float]) -> dict[int, float]:
    output: dict[int, float] = {}
    closes = [candle.close for candle in candles]
    for horizon, cost_bps in cost_bps_by_horizon.items():
        entry_closes = closes[: len(closes) - horizon]
        if not entry_closes:
            continue
        mean_entry_close = sum(entry_closes) / len(entry_closes)
        output[horizon] = mean_entry_close * cost_bps / 10000
    return output


def _checkpoint_horizons(horizons: list[int]) -> list[int]:
    if not horizons:
        return []
    horizon_set = set(horizons)
    selected_horizons = [horizon for horizon in DEFAULT_REPORT_HORIZON_CHECKPOINTS if horizon in horizon_set]
    for horizon in (horizons[0], horizons[-1]):
        if horizon not in selected_horizons:
            selected_horizons.append(horizon)
    return _unique_ordered(selected_horizons)


def _horizon_range_label(horizons: list[int], candle_minutes: int) -> str:
    if not horizons:
        return "none"
    first = horizons[0]
    last = horizons[-1]
    if first == last:
        return _format_horizon(first, candle_minutes)
    return f"{len(horizons)} ticks, {_format_horizon(first, candle_minutes)} to {_format_horizon(last, candle_minutes)}"


def _unique_ordered(values: list[Any]) -> list[Any]:
    seen = set()
    output: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


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


def _tail_summary_rows(summaries: list[TailEventSummary], horizons: list[int], candle_minutes: int) -> str:
    horizon_headers = "".join(f"<th>{_escape('Dir ' + _format_horizon(horizon, candle_minutes))}</th>" for horizon in horizons)
    header = (
        "<tr><th>Source</th><th>Signal</th><th>Tail</th><th>Count</th><th>Share</th>"
        "<th>Mean Signal</th><th>Mean Close</th><th>Prev Tick Move</th><th>Lookback Move</th><th>Range</th>"
        f"{horizon_headers}</tr>"
    )
    rows = "".join(
        "<tr>"
        f"<td>{_escape(summary.signal_source)}</td>"
        f"<td>{_escape(summary.signal_label)}</td>"
        f"<td>{_escape(summary.tail)}</td>"
        f"<td>{summary.count}</td>"
        f"<td>{_escape(_format_value(summary.share_pct))}%</td>"
        f"<td>{_escape(_format_value(summary.mean_signal))}</td>"
        f"<td>{_escape(_format_value(summary.mean_close))}</td>"
        f"<td>{_escape(_format_price_delta(summary.mean_one_tick_price_change))}</td>"
        f"<td>{_escape(_format_price_delta(summary.mean_lookback_price_change))}</td>"
        f"<td>{_escape(_format_price_delta(summary.mean_range_price))}</td>"
        + "".join(f"<td>{_escape(_format_price_delta(summary.forward_mean_directional_price_changes.get(horizon)))}</td>" for horizon in horizons)
        + "</tr>"
        for summary in summaries
    )
    return header + rows


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


def _format_price_delta(value: Any) -> str:
    if value is None:
        return "warming"
    return f"{value:+,.4f}"


def _escape(value: str) -> str:
    return html.escape(value, quote=True)