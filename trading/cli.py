from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factors import CROSS_ASSET_FACTOR_SIGNAL_NAMES, CROSS_MARKET_FACTOR_SIGNAL_NAMES, DEFAULT_FACTOR_SIGNAL_NAMES, compute_factor_series
from models import ModelShapeConfig, TrainingConfig, train_baseline_model
from backtest.engine import BacktestEngine
from backtest.pair import PairBacktestConfig, PairBacktestEngine, default_pair_backtest_report_path, write_pair_backtest_report
from trading.analysis import default_analysis_report_path, default_factor_report_root, parse_factor_names, parse_horizons, write_analysis_report, write_factor_group_reports
from trading.broker import JupiterCliPerpsBroker
from trading.config import AppConfig, DEFAULT_MARKETS_PATH, ExecutionConfig, PROJECT_ROOT
from trading.data import (
    JupiterPriceClient,
    enrich_candles_with_pyth_confidence,
    fetch_binance_spot_candles,
    fetch_coinbase_history_paginated,
    fetch_coinbase_spot_price,
    fetch_kraken_history_paginated,
    fetch_kraken_spot_candles,
    fetch_pyth_history_paginated,
    fetch_pyth_spot_price,
    load_candles,
    load_dataset_meta,
    parse_interval_minutes,
    update_canonical_with_price,
    write_dataset,
)
from trading.executor import LiveTradingExecutor
from trading.plotting import default_plot_path, load_meta_for_chart, write_mid_price_chart
from trading.storage import count_weekly_open_trades, load_position
from trading.strategy import SwingPerpsStrategy


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = AppConfig.from_env(market_name=getattr(args, "market", None), markets_path=getattr(args, "markets_config", DEFAULT_MARKETS_PATH))
    if args.command == "collect-once":
        collect_once(args, config)
    elif args.command == "fetch-history":
        fetch_history(args, config)
    elif args.command == "fetch-history-range":
        fetch_history_range(args, config)
    elif args.command == "backtest":
        run_backtest(args, config)
    elif args.command == "pair-backtest":
        run_pair_backtest(args, config)
    elif args.command == "signal":
        print_signal(args, config)
    elif args.command == "plot":
        plot_mid_price(args, config)
    elif args.command == "analyze":
        analyze_market(args, config)
    elif args.command == "enrich-pyth-confidence":
        enrich_pyth_confidence(args, config)
    elif args.command == "train-model":
        train_model(args, config)
    elif args.command == "run-once":
        run_once(args, config)
    elif args.command == "positions":
        print_positions(config.execution)
    else:
        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--market", default=None, help="market key from config/markets.json, e.g. SOL/BTC/ETH")
    common_parser.add_argument("--markets-config", type=Path, default=DEFAULT_MARKETS_PATH)

    parser = argparse.ArgumentParser(description="Medium-slow Jupiter perps trader.")
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect-once", parents=[common_parser], help="sample one configured market price into a canonical candle CSV")
    collect_parser.add_argument("--out", type=Path, default=None)
    collect_parser.add_argument("--minutes", type=int, default=None)

    history_parser = subparsers.add_parser("fetch-history", parents=[common_parser], help="download spot candles for rough research (single API call)")
    history_parser.add_argument("--out", type=Path, default=None)
    history_parser.add_argument("--source", choices=["kraken", "binance"], default="kraken")
    history_parser.add_argument("--pair", default=None)
    history_parser.add_argument("--symbol", default=None)
    history_parser.add_argument("--interval", default=None, help="override configured candle interval, e.g. 15m/30m/1h")
    history_parser.add_argument("--limit", type=int, default=500)

    range_parser = subparsers.add_parser(
        "fetch-history-range",
        parents=[common_parser],
        help="download a multi-day window of OHLCV and write the canonical schema (default source: Pyth)",
    )
    range_parser.add_argument("--out", type=Path, default=None)
    range_parser.add_argument("--source", choices=["pyth", "coinbase", "kraken"], default="pyth",
                              help="pyth = Jupiter oracle benchmark; coinbase = pageable CEX OHLC fallback; kraken = capped at ~720 bars")
    range_parser.add_argument("--coinbase-product", default=None)
    range_parser.add_argument("--pyth-symbol", default=None)
    range_parser.add_argument("--pyth-price-id", default=None)
    range_parser.add_argument("--pair", default=None, help="Kraken pair (only used when --source kraken)")
    range_parser.add_argument("--interval", default=None, help="override configured candle interval, e.g. 15m/30m/1h")
    range_parser.add_argument("--days", type=int, default=200)
    range_parser.add_argument("--symbol", default=None, help="logical symbol stored in meta sidecar")
    range_parser.add_argument("--instrument", default=None, help="target trading instrument (Jupiter perps market)")

    backtest_parser = subparsers.add_parser("backtest", parents=[common_parser], help="run a local CSV backtest")
    backtest_parser.add_argument("--data", type=Path, default=None)

    pair_backtest_parser = subparsers.add_parser("pair-backtest", parents=[common_parser], help="run a two-leg SOL/reference mean-reversion backtest")
    pair_backtest_parser.add_argument("--data", type=Path, default=None)
    pair_backtest_parser.add_argument("--reference-market", default="ETH", help="configured reference market, e.g. ETH")
    pair_backtest_parser.add_argument("--reference-data", type=Path, default=None, help="explicit reference candle CSV")
    pair_backtest_parser.add_argument("--interval", default=None, help="dataset interval, e.g. 5m or 15m")
    pair_backtest_parser.add_argument("--out", type=Path, default=None)
    pair_backtest_parser.add_argument("--entry-z", type=float, default=2.0)
    pair_backtest_parser.add_argument("--entry-tail-fraction", type=float, default=0.0, help="when positive, enter only current live top/bottom tail signals, e.g. 0.01 = top/bottom 1%%")
    pair_backtest_parser.add_argument("--regression-lookback", type=int, default=96, help="rolling regression/correlation lookback in ticks")
    pair_backtest_parser.add_argument("--exit-z", type=float, default=0.25)
    pair_backtest_parser.add_argument("--stop-z", type=float, default=4.0)
    pair_backtest_parser.add_argument("--min-corr", type=float, default=0.75)
    pair_backtest_parser.add_argument("--max-hold-ticks", type=int, default=96)
    pair_backtest_parser.add_argument("--cooldown-ticks", type=int, default=10)
    pair_backtest_parser.add_argument("--gross-exposure-usd", type=float, default=None, help="gross notional across both legs; defaults to equity * default leverage")
    pair_backtest_parser.add_argument("--fee-bps", type=float, default=None, help="per-side fee bps per leg; defaults to TRADER_FEE_BPS")
    pair_backtest_parser.add_argument("--hourly-cost-bps", type=float, default=0.0, help="estimated carry/funding cost in bps per hour on gross exposure")
    pair_backtest_parser.add_argument("--max-weekly-trades", type=int, default=None, help="0 disables the weekly pair-entry cap; defaults to risk config")

    signal_parser = subparsers.add_parser("signal", parents=[common_parser], help="print the current strategy signal")
    signal_parser.add_argument("--data", type=Path, default=None)

    plot_parser = subparsers.add_parser("plot", parents=[common_parser], help="write a Plotly mid-price chart from canonical market data")
    plot_parser.add_argument("--data", type=Path, default=None)
    plot_parser.add_argument("--out", type=Path, default=None)
    plot_parser.add_argument("--no-candles", action="store_true", help="hide OHLC candles and show only mid-price lines")
    plot_parser.add_argument("--no-ema", action="store_true", help="hide EMA overlays")

    analyze_parser = subparsers.add_parser("analyze", parents=[common_parser], help="write an HTML factor signal analysis report")
    analyze_parser.add_argument("--data", type=Path, default=None)
    analyze_parser.add_argument("--out", type=Path, default=None)
    analyze_parser.add_argument("--interval", default=None, help="analyze a non-default dataset interval, e.g. 15m uses data/<market>_usd_15m.csv when --data is omitted")
    analyze_parser.add_argument("--horizons", default=None, help="forward sampling ticks, e.g. 1-240 or 1,2,4,8,16")
    analyze_parser.add_argument("--factor-signals", default=None, help="comma-separated factor names to include as signals")
    analyze_parser.add_argument("--round-trip-cost-bps", type=float, default=None, help="round-trip trading cost in bps; defaults to 2 * TRADER_FEE_BPS")
    analyze_parser.add_argument("--hourly-cost-bps", type=float, default=0.0, help="estimated carry/funding cost in bps per hour")
    analyze_parser.add_argument("--tail-fraction", type=float, default=0.01, help="tail fraction for large-signal event analysis, e.g. 0.01 = top/bottom 1%%")
    analyze_parser.add_argument("--tail-lookback-ticks", type=int, default=48, help="lookback ticks used to describe market state around tail events")
    analyze_parser.add_argument("--group-by-factor-family", action="store_true", help="write one report per factor family under reports/factors/<family>; --out is treated as the output root")
    analyze_parser.add_argument("--reference-market", default=None, help="load a configured reference market, e.g. ETH, for cross-asset factors")
    analyze_parser.add_argument("--reference-markets", default=None, help="comma-separated configured reference markets, e.g. ETH,BTC, for basket factors")
    analyze_parser.add_argument("--reference-data", type=Path, default=None, help="explicit reference market candle CSV for cross-asset factors")
    analyze_parser.add_argument("--tail-filter-factor", default=None, help="optional factor name used to filter eligible tail events, e.g. cross_market_corr_min")
    analyze_parser.add_argument("--tail-filter-min", type=float, default=None, help="minimum raw factor value for --tail-filter-factor")
    analyze_parser.add_argument("--tail-filter-max", type=float, default=None, help="maximum raw factor value for --tail-filter-factor")
    analyze_parser.add_argument("--tail-dedup-ticks", type=int, default=0, help="when positive, keep only the first tail event in each dense N-tick cluster")

    enrich_parser = subparsers.add_parser("enrich-pyth-confidence", parents=[common_parser], help="sample Hermes confidence near candle close times and write optional oracle columns")
    enrich_parser.add_argument("--data", type=Path, default=None)
    enrich_parser.add_argument("--out", type=Path, default=None, help="defaults to overwriting --data/configured data path")
    enrich_parser.add_argument("--interval", default=None, help="dataset interval, e.g. 5m/15m; used to query candle-close snapshots")
    enrich_parser.add_argument("--days", type=int, default=14, help="number of trailing days to enrich")
    enrich_parser.add_argument("--pyth-price-id", default=None)
    enrich_parser.add_argument("--max-workers", type=int, default=1)
    enrich_parser.add_argument("--sleep-seconds", type=float, default=0.2, help="sequential throttle when --max-workers is 1")
    enrich_parser.add_argument("--overwrite", action="store_true", help="re-fetch confidence for rows that already have Pyth confidence")

    train_parser = subparsers.add_parser("train-model", parents=[common_parser], help="build the baseline model training dataset and print a training scaffold summary")
    train_parser.add_argument("--data", type=Path, default=None)
    train_parser.add_argument("--target-horizon", type=int, default=4, help="forward sampling ticks used as the training target")
    train_parser.add_argument("--train-fraction", type=float, default=0.70)
    train_parser.add_argument("--min-samples", type=int, default=200)

    run_parser = subparsers.add_parser("run-once", parents=[common_parser], help="evaluate one decision and optionally send it to Jupiter CLI")
    run_parser.add_argument("--data", type=Path, default=None)
    run_parser.add_argument("--live", action="store_true", help="allow non-dry-run execution")
    run_parser.add_argument("--paper", action="store_true", help="force the built-in dry-run broker")

    subparsers.add_parser("positions", parents=[common_parser], help="print Jupiter perps positions through the CLI")
    return parser


def data_path_from_args(args: argparse.Namespace, config: AppConfig, attr: str = "data") -> Path:
    path = getattr(args, attr, None)
    return path if path is not None else config.strategy.data_path


def analysis_data_path_from_args(args: argparse.Namespace, config: AppConfig, interval_minutes: int | None) -> Path:
    if args.data is not None:
        return args.data
    if interval_minutes is None:
        return config.strategy.data_path
    interval_text = interval_string_from_minutes(interval_minutes)
    return PROJECT_ROOT / "data" / f"{config.strategy.market.lower()}_usd_{interval_text}.csv"


def reference_data_path_from_args(args: argparse.Namespace, config: AppConfig, interval_minutes: int | None) -> Path | None:
    if args.reference_data is not None:
        return args.reference_data
    if not args.reference_market:
        return None
    reference_key = str(args.reference_market).lower()
    reference_interval = interval_minutes or config.strategy.candle_minutes
    interval_text = interval_string_from_minutes(reference_interval)
    return PROJECT_ROOT / "data" / f"{reference_key}_usd_{interval_text}.csv"


def reference_data_paths_from_args(args: argparse.Namespace, config: AppConfig, interval_minutes: int | None) -> dict[str, Path]:
    if args.reference_data is not None:
        reference_key = str(args.reference_market or "REFERENCE").upper()
        return {reference_key: args.reference_data}
    raw_reference_markets = args.reference_markets or args.reference_market
    if not raw_reference_markets:
        return {}
    reference_interval = interval_minutes or config.strategy.candle_minutes
    interval_text = interval_string_from_minutes(reference_interval)
    paths: dict[str, Path] = {}
    for item in str(raw_reference_markets).split(","):
        reference_key = item.strip().upper()
        if reference_key:
            paths[reference_key] = PROJECT_ROOT / "data" / f"{reference_key.lower()}_usd_{interval_text}.csv"
    return paths


def default_analysis_output_path(market: str, interval_minutes: int | None) -> Path:
    if interval_minutes is None:
        return PROJECT_ROOT / default_analysis_report_path(market)
    interval_text = interval_string_from_minutes(interval_minutes)
    return PROJECT_ROOT / "reports" / f"{market.lower()}_{interval_text}_analysis.html"


def interval_minutes_from_args(args: argparse.Namespace, config: AppConfig) -> int:
    raw_interval = getattr(args, "interval", None)
    return parse_interval_minutes(raw_interval) if raw_interval else config.strategy.candle_minutes


def interval_string_from_minutes(minutes: int) -> str:
    if minutes % (60 * 24) == 0:
        return f"{minutes // (60 * 24)}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def collect_once(args: argparse.Namespace, config: AppConfig) -> None:
    minutes = args.minutes or config.strategy.candle_minutes
    out_path = data_path_from_args(args, config, "out")
    if config.strategy.price_source == "coinbase":
        price = fetch_coinbase_spot_price(config.strategy.coinbase_product)
        source = f"coinbase-spot:{config.strategy.coinbase_product}"
    elif config.strategy.price_source == "pyth":
        if not config.strategy.pyth_price_id:
            raise SystemExit(f"market {config.strategy.market} is missing pyth_price_id")
        price = fetch_pyth_spot_price(config.strategy.pyth_price_id)
        source = f"pyth-hermes:{config.strategy.pyth_price_id}"
    elif config.strategy.price_source == "jupiter":
        if not config.strategy.price_mint:
            raise SystemExit(f"market {config.strategy.market} is missing price_mint for Jupiter Price API")
        client = JupiterPriceClient(api_key=config.execution.jupiter_api_key, base_url=config.execution.jupiter_base_url)
        price = client.get_price_usd(config.strategy.price_mint)
        source = "jupiter-price-v3"
    else:
        raise SystemExit(f"unsupported price_source '{config.strategy.price_source}' for market {config.strategy.market}")
    candle = update_canonical_with_price(
        out_path,
        price,
        interval_minutes=minutes,
        symbol=config.strategy.symbol,
        instrument=config.strategy.instrument,
        source=source,
    )
    print(json.dumps({"price": price, "candle": candle.to_csv_row()}, indent=2))


def fetch_history(args: argparse.Namespace, config: AppConfig) -> None:
    interval_minutes = interval_minutes_from_args(args, config)
    out_path = data_path_from_args(args, config, "out")
    if args.source == "binance":
        symbol = args.symbol or config.strategy.binance_symbol
        candles = fetch_binance_spot_candles(symbol=symbol, interval=args.interval or interval_string_from_minutes(interval_minutes), limit=args.limit)
        source_label = f"binance-spot:{symbol}"
    else:
        pair = args.pair or config.strategy.kraken_pair
        candles = fetch_kraken_spot_candles(pair=pair, interval_minutes=interval_minutes, limit=args.limit)
        source_label = f"kraken-spot:{pair}"
    meta = write_dataset(
        out_path,
        candles,
        symbol=config.strategy.symbol,
        instrument=config.strategy.instrument,
        venue="jupiter-perps",
        interval_minutes=interval_minutes,
        source=source_label,
    )
    print(json.dumps({"written": len(candles), "path": str(out_path), "meta": meta.to_json_dict()}, indent=2))


def fetch_history_range(args: argparse.Namespace, config: AppConfig) -> None:
    interval_minutes = interval_minutes_from_args(args, config)
    out_path = data_path_from_args(args, config, "out")
    if args.source == "kraken":
        pair = args.pair or config.strategy.kraken_pair
        candles = fetch_kraken_history_paginated(
            pair=pair,
            interval_minutes=interval_minutes,
            days=args.days,
        )
        source_label = f"kraken-spot:{pair}"
        notes = f"paginated, requested_days={args.days} (Kraken caps at ~720 bars)"
    elif args.source == "coinbase":
        product = args.coinbase_product or config.strategy.coinbase_product
        candles = fetch_coinbase_history_paginated(
            product_id=product,
            interval_minutes=interval_minutes,
            days=args.days,
        )
        source_label = f"coinbase-spot:{product}"
        notes = f"paginated, requested_days={args.days}"
    else:
        pyth_symbol = args.pyth_symbol or config.strategy.pyth_symbol
        pyth_price_id = args.pyth_price_id or config.strategy.pyth_price_id
        candles = fetch_pyth_history_paginated(
            symbol=pyth_symbol,
            interval_minutes=interval_minutes,
            days=args.days,
        )
        source_label = f"pyth-benchmarks:{pyth_symbol}"
        notes = f"paginated, requested_days={args.days}; pyth_price_id={pyth_price_id}"
        extras = {"pyth_price_id": pyth_price_id} if pyth_price_id else None
        meta = write_dataset(
            out_path,
            candles,
            symbol=args.symbol or config.strategy.symbol,
            instrument=args.instrument or config.strategy.instrument,
            venue="jupiter-perps",
            interval_minutes=interval_minutes,
            source=source_label,
            notes=notes,
            extras=extras,
        )
        print(json.dumps({"written": len(candles), "path": str(out_path), "meta": meta.to_json_dict()}, indent=2))
        return
    meta = write_dataset(
        out_path,
        candles,
        symbol=args.symbol or config.strategy.symbol,
        instrument=args.instrument or config.strategy.instrument,
        venue="jupiter-perps",
        interval_minutes=interval_minutes,
        source=source_label,
        notes=notes,
    )
    print(json.dumps({"written": len(candles), "path": str(out_path), "meta": meta.to_json_dict()}, indent=2))


def run_backtest(args: argparse.Namespace, config: AppConfig) -> None:
    candles = load_candles(data_path_from_args(args, config))
    engine = BacktestEngine(config.strategy, config.risk)
    result = engine.run(candles)
    print(json.dumps(result.summary(), indent=2))


def run_pair_backtest(args: argparse.Namespace, config: AppConfig) -> None:
    interval_minutes = parse_interval_minutes(args.interval) if args.interval else config.strategy.candle_minutes
    data_path = analysis_data_path_from_args(args, config, interval_minutes)
    reference_key = str(args.reference_market or "ETH").upper()
    if args.reference_data is not None:
        reference_data_path = args.reference_data
    else:
        interval_text = interval_string_from_minutes(interval_minutes)
        reference_data_path = PROJECT_ROOT / "data" / f"{reference_key.lower()}_usd_{interval_text}.csv"
    primary_candles = load_candles(data_path)
    reference_candles = load_candles(reference_data_path)
    if not primary_candles:
        raise SystemExit(f"no primary candles found at {data_path}")
    if not reference_candles:
        raise SystemExit(f"no reference candles found at {reference_data_path}")

    pair_config = PairBacktestConfig(
        primary_label=config.strategy.market,
        reference_label=reference_key,
        candle_minutes=interval_minutes,
        entry_z=args.entry_z,
        entry_tail_fraction=args.entry_tail_fraction,
        regression_lookback=args.regression_lookback,
        exit_z=args.exit_z,
        stop_z=args.stop_z,
        min_corr=args.min_corr,
        max_hold_ticks=args.max_hold_ticks,
        cooldown_ticks=args.cooldown_ticks,
        gross_exposure_usd=args.gross_exposure_usd or config.risk.equity_usd * config.risk.default_leverage,
        fee_bps=args.fee_bps if args.fee_bps is not None else config.risk.fee_bps,
        hourly_cost_bps=args.hourly_cost_bps,
        max_weekly_trades=args.max_weekly_trades if args.max_weekly_trades is not None else config.risk.max_weekly_trades,
    )
    engine = PairBacktestEngine(config.strategy, config.risk, pair_config)
    result = engine.run(primary_candles, reference_candles)
    output_path = args.out or (PROJECT_ROOT / default_pair_backtest_report_path(config.strategy.market, reference_key, interval_minutes))
    written = write_pair_backtest_report(result, output_path)
    print(json.dumps({"summary": result.summary(), "report": str(written), "data": str(data_path), "reference_data": str(reference_data_path)}, indent=2))


def print_signal(args: argparse.Namespace, config: AppConfig) -> None:
    candles = load_candles(data_path_from_args(args, config))
    position = load_position(config.execution.state_path)
    weekly_count = count_weekly_open_trades(config.execution.trade_log_path, datetime.now(timezone.utc))
    strategy = SwingPerpsStrategy(config.strategy, config.risk)
    signal = strategy.analyze(candles, position, weekly_count)
    print(json.dumps(signal.__dict__, indent=2, default=str))


def plot_mid_price(args: argparse.Namespace, config: AppConfig) -> None:
    data_path = data_path_from_args(args, config)
    output_path = args.out or (PROJECT_ROOT / default_plot_path(config.strategy.market))
    candles = load_candles(data_path)
    if not candles:
        raise SystemExit(f"no candles found at {data_path}")
    written = write_mid_price_chart(
        candles,
        output_path,
        strategy_config=config.strategy,
        meta=load_meta_for_chart(data_path),
        include_candles=not args.no_candles,
        include_ema=not args.no_ema,
    )
    print(json.dumps({"written": str(written), "candles": len(candles), "mid_definition": "(high + low) / 2"}, indent=2))


def analyze_market(args: argparse.Namespace, config: AppConfig) -> None:
    interval_minutes = parse_interval_minutes(args.interval) if args.interval else None
    data_path = analysis_data_path_from_args(args, config, interval_minutes)
    reference_data_paths = reference_data_paths_from_args(args, config, interval_minutes)
    reference_data_path = next(iter(reference_data_paths.values()), None)
    output_path = args.out or default_analysis_output_path(config.strategy.market, interval_minutes)
    candles = load_candles(data_path)
    if not candles:
        raise SystemExit(f"no candles found at {data_path}")
    reference_candles_by_name = {name: load_candles(path) for name, path in reference_data_paths.items()}
    for name, path in reference_data_paths.items():
        if not reference_candles_by_name[name]:
            raise SystemExit(f"no reference candles found for {name} at {path}")
    reference_candles = next(iter(reference_candles_by_name.values()), None)
    reference_label = ", ".join(f"{name}={path}" for name, path in reference_data_paths.items()) or None
    factor_names = parse_factor_names(args.factor_signals)
    if reference_candles_by_name and factor_names is None:
        factor_names = list(DEFAULT_FACTOR_SIGNAL_NAMES) + list(CROSS_ASSET_FACTOR_SIGNAL_NAMES)
        if {"ETH", "BTC"}.issubset(reference_candles_by_name):
            factor_names += list(CROSS_MARKET_FACTOR_SIGNAL_NAMES)
    if args.group_by_factor_family:
        output_root = args.out or (PROJECT_ROOT / default_factor_report_root())
        written = write_factor_group_reports(
            candles,
            output_root,
            config=config,
            data_path=data_path,
            reference_candles=reference_candles,
            reference_candles_by_name=reference_candles_by_name,
            reference_data_path=reference_label,
            meta=load_meta_for_chart(data_path),
            horizons=parse_horizons(args.horizons),
            factor_names=factor_names,
            round_trip_cost_bps=args.round_trip_cost_bps,
            hourly_cost_bps=args.hourly_cost_bps,
            tail_fraction=args.tail_fraction,
            tail_lookback_ticks=args.tail_lookback_ticks,
            tail_filter_factor=args.tail_filter_factor,
            tail_filter_min=args.tail_filter_min,
            tail_filter_max=args.tail_filter_max,
            tail_dedup_ticks=args.tail_dedup_ticks,
            candle_minutes=interval_minutes,
        )
        print(json.dumps({"written": [str(path) for path in written], "candles": len(candles)}, indent=2))
        return
    written = write_analysis_report(
        candles,
        output_path,
        config=config,
        data_path=data_path,
        reference_candles=reference_candles,
        reference_candles_by_name=reference_candles_by_name,
        reference_data_path=reference_label,
        meta=load_meta_for_chart(data_path),
        horizons=parse_horizons(args.horizons),
        factor_names=factor_names,
        round_trip_cost_bps=args.round_trip_cost_bps,
        hourly_cost_bps=args.hourly_cost_bps,
        tail_fraction=args.tail_fraction,
        tail_lookback_ticks=args.tail_lookback_ticks,
        tail_filter_factor=args.tail_filter_factor,
        tail_filter_min=args.tail_filter_min,
        tail_filter_max=args.tail_filter_max,
        tail_dedup_ticks=args.tail_dedup_ticks,
        candle_minutes=interval_minutes,
    )
    print(json.dumps({"written": str(written), "candles": len(candles)}, indent=2))


def enrich_pyth_confidence(args: argparse.Namespace, config: AppConfig) -> None:
    interval_minutes = interval_minutes_from_args(args, config)
    data_path = analysis_data_path_from_args(args, config, interval_minutes)
    out_path = args.out or data_path
    price_id = args.pyth_price_id or config.strategy.pyth_price_id
    if not price_id:
        raise SystemExit(f"market {config.strategy.market} is missing pyth_price_id")
    candles = load_candles(data_path)
    if not candles:
        raise SystemExit(f"no candles found at {data_path}")
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    enriched = enrich_candles_with_pyth_confidence(
        candles,
        price_id,
        interval_minutes=interval_minutes,
        since=since,
        max_workers=args.max_workers,
        sleep_seconds=args.sleep_seconds,
        overwrite=args.overwrite,
    )
    enriched_count = sum(1 for candle in enriched if candle.timestamp >= since and candle.pyth_confidence is not None)
    existing_meta = load_dataset_meta(data_path)
    extras = dict(existing_meta.extras) if existing_meta else {}
    extras.update(
        {
            "pyth_confidence_price_id": price_id,
            "pyth_confidence_days": args.days,
            "pyth_confidence_since": since.isoformat(),
            "pyth_confidence_enriched_count": enriched_count,
        }
    )
    meta = write_dataset(
        out_path,
        enriched,
        symbol=existing_meta.symbol if existing_meta else config.strategy.symbol,
        instrument=existing_meta.instrument if existing_meta else config.strategy.instrument,
        venue=existing_meta.venue if existing_meta else "jupiter-perps",
        interval_minutes=interval_minutes,
        source=existing_meta.source if existing_meta else f"pyth-hermes:{price_id}",
        notes=_append_note_once(existing_meta.notes if existing_meta else "", "pyth_confidence_enriched"),
        extras=extras,
    )
    print(json.dumps({"written": len(enriched), "enriched": enriched_count, "path": str(out_path), "meta": meta.to_json_dict()}, indent=2))


def _append_note_once(notes: str, note: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for part in [item.strip() for item in notes.split(";") if item.strip()] + [note]:
        if part in seen:
            continue
        seen.add(part)
        parts.append(part)
    return "; ".join(parts)


def train_model(args: argparse.Namespace, config: AppConfig) -> None:
    data_path = data_path_from_args(args, config)
    candles = load_candles(data_path)
    if not candles:
        raise SystemExit(f"no candles found at {data_path}")
    shape = ModelShapeConfig(target_horizon_ticks=args.target_horizon)
    training_config = TrainingConfig(shape=shape, train_fraction=args.train_fraction, min_samples=args.min_samples)
    factors = compute_factor_series(candles, config.strategy)
    result = train_baseline_model(candles, factors, training_config)
    print(json.dumps(asdict(result), indent=2, default=str))


def run_once(args: argparse.Namespace, config: AppConfig) -> None:
    data_path = data_path_from_args(args, config)
    candles = load_candles(data_path)
    if not candles:
        raise SystemExit(f"no candles found at {data_path}")

    execution_config = config.execution
    if args.live:
        execution_config = replace(execution_config, dry_run=False)
    if args.paper:
        execution_config = replace(execution_config, dry_run=True)

    executor = LiveTradingExecutor.from_config(config, execution_config)
    result = executor.run_once(candles)
    print(
        json.dumps(
            {
                "signal": result.inference.signal.__dict__,
                "model_signals": [_research_signal_summary(signal) for signal in result.inference.model_signals],
                "factor_ready": result.inference.factor_ready,
                "order": result.decision.order.__dict__ if result.decision.order else None,
                "blocked": result.decision.blocked_reason,
                "report": result.report.__dict__ if result.report else None,
            },
            indent=2,
            default=str,
        )
    )


def _research_signal_summary(signal: object) -> dict[str, object]:
    latest_value = signal.latest_value() if hasattr(signal, "latest_value") else None
    return {
        "name": getattr(signal, "name", ""),
        "label": getattr(signal, "label", ""),
        "source": getattr(signal, "source", ""),
        "group": getattr(signal, "group", ""),
        "latest": latest_value,
        "normalization": getattr(signal, "normalization", ""),
    }


def print_positions(execution_config: ExecutionConfig) -> None:
    broker = JupiterCliPerpsBroker(execution_config)
    print(json.dumps(broker.positions(), indent=2, default=str))
