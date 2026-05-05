from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from backtest.engine import BacktestEngine
from trading.broker import DryRunBroker, JupiterCliPerpsBroker
from trading.config import AppConfig, DEFAULT_MARKETS_PATH, ExecutionConfig, PROJECT_ROOT
from trading.data import (
    JupiterPriceClient,
    fetch_binance_spot_candles,
    fetch_coinbase_history_paginated,
    fetch_coinbase_spot_price,
    fetch_kraken_history_paginated,
    fetch_kraken_spot_candles,
    fetch_pyth_history_paginated,
    fetch_pyth_spot_price,
    load_candles,
    parse_interval_minutes,
    update_canonical_with_price,
    write_dataset,
)
from trading.models import ExecutionReport, OrderIntent, Position, SignalAction
from trading.plotting import default_plot_path, load_meta_for_chart, write_mid_price_chart
from trading.risk import RiskError, RiskManager
from trading.storage import append_trade_log, count_weekly_open_trades, daily_realized_pnl, load_position, save_position
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
    elif args.command == "signal":
        print_signal(args, config)
    elif args.command == "plot":
        plot_mid_price(args, config)
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

    signal_parser = subparsers.add_parser("signal", parents=[common_parser], help="print the current strategy signal")
    signal_parser.add_argument("--data", type=Path, default=None)

    plot_parser = subparsers.add_parser("plot", parents=[common_parser], help="write a Plotly mid-price chart from canonical market data")
    plot_parser.add_argument("--data", type=Path, default=None)
    plot_parser.add_argument("--out", type=Path, default=None)
    plot_parser.add_argument("--no-candles", action="store_true", help="hide OHLC candles and show only mid-price lines")
    plot_parser.add_argument("--no-ema", action="store_true", help="hide EMA overlays")

    run_parser = subparsers.add_parser("run-once", parents=[common_parser], help="evaluate one decision and optionally send it to Jupiter CLI")
    run_parser.add_argument("--data", type=Path, default=None)
    run_parser.add_argument("--live", action="store_true", help="allow non-dry-run execution")
    run_parser.add_argument("--paper", action="store_true", help="force the built-in dry-run broker")

    subparsers.add_parser("positions", parents=[common_parser], help="print Jupiter perps positions through the CLI")
    return parser


def data_path_from_args(args: argparse.Namespace, config: AppConfig, attr: str = "data") -> Path:
    path = getattr(args, attr, None)
    return path if path is not None else config.strategy.data_path


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

    now = datetime.now(timezone.utc)
    open_position = load_position(execution_config.state_path)
    weekly_count = count_weekly_open_trades(execution_config.trade_log_path, now)
    daily_pnl = daily_realized_pnl(execution_config.trade_log_path, now)
    strategy = SwingPerpsStrategy(config.strategy, config.risk)
    risk_manager = RiskManager(config.strategy, config.risk)
    signal = strategy.analyze(candles, open_position, weekly_count)

    try:
        order = risk_manager.order_from_signal(signal, candles[-1].timestamp, weekly_count, daily_pnl, open_position)
    except RiskError as exc:
        print(json.dumps({"signal": signal.__dict__, "blocked": str(exc)}, indent=2, default=str))
        return
    if order is None:
        print(json.dumps({"signal": signal.__dict__, "order": None}, indent=2, default=str))
        return

    broker = DryRunBroker() if execution_config.dry_run else JupiterCliPerpsBroker(execution_config)
    report = broker.execute(order)
    realized_pnl = 0.0
    if order.action == SignalAction.CLOSE and open_position is not None:
        realized_pnl = open_position.unrealized_pnl_usd(candles[-1].close)
    append_trade_log(execution_config.trade_log_path, order, report, realized_pnl)
    update_state_after_execution(execution_config, order, report, candles[-1].timestamp)
    print(json.dumps({"signal": signal.__dict__, "order": order.__dict__, "report": report.__dict__}, indent=2, default=str))


def update_state_after_execution(execution_config: ExecutionConfig, order: OrderIntent, report: ExecutionReport, opened_at: datetime) -> None:
    if not report.accepted:
        return
    if order.action == SignalAction.OPEN:
        position = Position(
            side=order.side,
            entry_price=order.entry_price or 0.0,
            size_usd=order.size_usd,
            collateral_usd=order.collateral_usd,
            leverage=order.leverage,
            opened_at=opened_at,
            stop_loss=order.stop_loss or 0.0,
            take_profit=order.take_profit or 0.0,
            position_id=report.position_id,
        )
        save_position(execution_config.state_path, position)
    elif order.action == SignalAction.CLOSE:
        save_position(execution_config.state_path, None)


def print_positions(execution_config: ExecutionConfig) -> None:
    broker = JupiterCliPerpsBroker(execution_config)
    print(json.dumps(broker.positions(), indent=2, default=str))
