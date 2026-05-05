from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from backtest.engine import BacktestEngine
from trading.broker import DryRunBroker, JupiterCliPerpsBroker
from trading.config import AppConfig, ExecutionConfig, PROJECT_ROOT
from trading.data import JupiterPriceClient, fetch_binance_spot_candles, fetch_kraken_spot_candles, load_candles, parse_interval_minutes, update_candle_with_price, write_candles
from trading.models import ExecutionReport, OrderIntent, Position, SignalAction
from trading.risk import RiskError, RiskManager
from trading.storage import append_trade_log, count_weekly_open_trades, daily_realized_pnl, load_position, save_position
from trading.strategy import SwingPerpsStrategy


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = AppConfig.from_env()
    if args.command == "collect-once":
        collect_once(args, config)
    elif args.command == "fetch-history":
        fetch_history(args)
    elif args.command == "backtest":
        run_backtest(args, config)
    elif args.command == "signal":
        print_signal(args, config)
    elif args.command == "run-once":
        run_once(args, config)
    elif args.command == "positions":
        print_positions(config.execution)
    else:
        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Medium-slow SOL perps trader for Jupiter.")
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect-once", help="sample one Jupiter SOL price into a candle CSV")
    collect_parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "sol_usd_30m.csv")
    collect_parser.add_argument("--minutes", type=int, default=None)

    history_parser = subparsers.add_parser("fetch-history", help="download spot candles for rough research")
    history_parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "sol_usd_30m_history.csv")
    history_parser.add_argument("--source", choices=["kraken", "binance"], default="kraken")
    history_parser.add_argument("--pair", default="SOLUSD")
    history_parser.add_argument("--symbol", default="SOLUSDT")
    history_parser.add_argument("--interval", default="30m")
    history_parser.add_argument("--limit", type=int, default=500)

    backtest_parser = subparsers.add_parser("backtest", help="run a local CSV backtest")
    backtest_parser.add_argument("--data", type=Path, required=True)

    signal_parser = subparsers.add_parser("signal", help="print the current strategy signal")
    signal_parser.add_argument("--data", type=Path, required=True)

    run_parser = subparsers.add_parser("run-once", help="evaluate one decision and optionally send it to Jupiter CLI")
    run_parser.add_argument("--data", type=Path, required=True)
    run_parser.add_argument("--live", action="store_true", help="allow non-dry-run execution")
    run_parser.add_argument("--paper", action="store_true", help="force the built-in dry-run broker")

    subparsers.add_parser("positions", help="print Jupiter perps positions through the CLI")
    return parser


def collect_once(args: argparse.Namespace, config: AppConfig) -> None:
    minutes = args.minutes or config.strategy.candle_minutes
    client = JupiterPriceClient(api_key=config.execution.jupiter_api_key, base_url=config.execution.jupiter_base_url)
    price = client.get_price_usd(config.strategy.price_mint)
    candle = update_candle_with_price(args.out, price, minutes)
    print(json.dumps({"price": price, "candle": candle.to_csv_row()}, indent=2))


def fetch_history(args: argparse.Namespace) -> None:
    if args.source == "binance":
        candles = fetch_binance_spot_candles(symbol=args.symbol, interval=args.interval, limit=args.limit)
    else:
        candles = fetch_kraken_spot_candles(pair=args.pair, interval_minutes=parse_interval_minutes(args.interval), limit=args.limit)
    write_candles(args.out, candles)
    print(json.dumps({"written": len(candles), "path": str(args.out)}, indent=2))


def run_backtest(args: argparse.Namespace, config: AppConfig) -> None:
    candles = load_candles(args.data)
    engine = BacktestEngine(config.strategy, config.risk)
    result = engine.run(candles)
    print(json.dumps(result.summary(), indent=2))


def print_signal(args: argparse.Namespace, config: AppConfig) -> None:
    candles = load_candles(args.data)
    position = load_position(config.execution.state_path)
    weekly_count = count_weekly_open_trades(config.execution.trade_log_path, datetime.now(timezone.utc))
    strategy = SwingPerpsStrategy(config.strategy, config.risk)
    signal = strategy.analyze(candles, position, weekly_count)
    print(json.dumps(signal.__dict__, indent=2, default=str))


def run_once(args: argparse.Namespace, config: AppConfig) -> None:
    candles = load_candles(args.data)
    if not candles:
        raise SystemExit(f"no candles found at {args.data}")

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
