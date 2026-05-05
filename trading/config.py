from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKETS_PATH = PROJECT_ROOT / "config" / "markets.json"


def load_env_file(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.strip()
        value = raw_value.strip().strip('"').strip("'")
        os.environ.setdefault(name, value)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return float(raw_value)


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return int(raw_value)


@dataclass(frozen=True)
class MarketConfig:
    name: str
    asset: str
    symbol: str
    instrument: str
    candle_minutes: int
    price_source: str
    price_mint: str
    data_path: Path
    coinbase_product: str
    kraken_pair: str
    binance_symbol: str
    pyth_symbol: str
    pyth_price_id: str


def _resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _parse_interval_minutes(raw_value: str | int) -> int:
    if isinstance(raw_value, int):
        return raw_value
    value = str(raw_value).strip().lower()
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("h"):
        return int(value[:-1]) * 60
    if value.endswith("d"):
        return int(value[:-1]) * 60 * 24
    return int(value)


def load_market_config(market_name: str | None = None, path: Path = DEFAULT_MARKETS_PATH) -> MarketConfig:
    if not path.exists():
        raise FileNotFoundError(f"market config not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    markets = payload.get("markets") or {}
    selected = (market_name or os.getenv("TRADER_MARKET") or payload.get("default_market") or "SOL").upper()
    raw_market = markets.get(selected)
    if raw_market is None:
        known = ", ".join(sorted(markets)) or "<none>"
        raise ValueError(f"unknown market '{selected}' in {path}; available: {known}")
    history = raw_market.get("history") or {}
    return MarketConfig(
        name=selected,
        asset=str(raw_market.get("asset", selected)).upper(),
        symbol=str(raw_market.get("symbol", f"{selected}/USD")),
        instrument=str(raw_market.get("instrument", f"{selected}-PERP")),
        candle_minutes=_parse_interval_minutes(raw_market.get("candle_interval", raw_market.get("candle_minutes", 30))),
        price_source=str(raw_market.get("price_source", "pyth")).lower(),
        price_mint=str(raw_market.get("price_mint", "")),
        data_path=_resolve_project_path(raw_market.get("data_path", f"data/{selected.lower()}_usd_30m.csv")),
        coinbase_product=str(history.get("coinbase_product", f"{selected}-USD")),
        kraken_pair=str(history.get("kraken_pair", f"{selected}USD")),
        binance_symbol=str(history.get("binance_symbol", f"{selected}USDT")),
        pyth_symbol=str(history.get("pyth_symbol", f"Crypto.{selected}/USD")),
        pyth_price_id=str(history.get("pyth_price_id", "")),
    )


@dataclass(frozen=True)
class StrategyConfig:
    market: str = "SOL"
    asset: str = "SOL"
    symbol: str = "SOL/USD"
    instrument: str = "SOL-PERP"
    price_source: str = "pyth"
    price_mint: str = WRAPPED_SOL_MINT
    data_path: Path = PROJECT_ROOT / "data" / "sol_usd_30m.csv"
    coinbase_product: str = "SOL-USD"
    kraken_pair: str = "SOLUSD"
    binance_symbol: str = "SOLUSDT"
    pyth_symbol: str = "Crypto.SOL/USD"
    pyth_price_id: str = "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"
    candle_minutes: int = 30
    fast_ema_period: int = 20
    slow_ema_period: int = 80
    rsi_period: int = 14
    atr_period: int = 14
    breakout_lookback: int = 20
    cooldown_bars: int = 4
    long_min_rsi: float = 45.0
    long_max_rsi: float = 78.0
    short_min_rsi: float = 22.0
    short_max_rsi: float = 55.0
    long_exit_rsi: float = 84.0
    short_exit_rsi: float = 16.0

    @classmethod
    def from_env(cls, market_config: MarketConfig | None = None) -> "StrategyConfig":
        if market_config is None:
            market_config = load_market_config()
        return cls(
            market=market_config.name,
            asset=market_config.asset,
            symbol=market_config.symbol,
            instrument=market_config.instrument,
            price_source=os.getenv("TRADER_PRICE_SOURCE", market_config.price_source),
            price_mint=os.getenv("TRADER_PRICE_MINT", market_config.price_mint),
            data_path=_resolve_project_path(os.getenv("TRADER_DATA_PATH", str(market_config.data_path))),
            coinbase_product=os.getenv("TRADER_COINBASE_PRODUCT", market_config.coinbase_product),
            kraken_pair=os.getenv("TRADER_KRAKEN_PAIR", market_config.kraken_pair),
            binance_symbol=os.getenv("TRADER_BINANCE_SYMBOL", market_config.binance_symbol),
            pyth_symbol=os.getenv("TRADER_PYTH_SYMBOL", market_config.pyth_symbol),
            pyth_price_id=os.getenv("TRADER_PYTH_PRICE_ID", market_config.pyth_price_id),
            candle_minutes=_env_int("TRADER_CANDLE_MINUTES", market_config.candle_minutes),
        )


@dataclass(frozen=True)
class RiskConfig:
    equity_usd: float = 1000.0
    risk_per_trade_pct: float = 0.01
    default_leverage: float = 2.0
    max_leverage: float = 3.0
    max_position_equity_pct: float = 0.50
    max_weekly_trades: int = 10
    max_daily_loss_pct: float = 0.03
    stop_atr_multiple: float = 2.0
    take_profit_atr_multiple: float = 3.2
    min_stop_pct: float = 0.015
    max_stop_pct: float = 0.06
    min_order_usd: float = 10.0
    fee_bps: float = 6.0

    @classmethod
    def from_env(cls) -> "RiskConfig":
        return cls(
            equity_usd=_env_float("TRADER_EQUITY_USD", 1000.0),
            risk_per_trade_pct=_env_float("TRADER_RISK_PER_TRADE_PCT", 0.01),
            default_leverage=_env_float("TRADER_DEFAULT_LEVERAGE", 2.0),
            max_leverage=_env_float("TRADER_MAX_LEVERAGE", 3.0),
            max_weekly_trades=_env_int("TRADER_MAX_WEEKLY_TRADES", 10),
            max_daily_loss_pct=_env_float("TRADER_MAX_DAILY_LOSS_PCT", 0.03),
        )


@dataclass(frozen=True)
class ExecutionConfig:
    jupiter_api_key: str = ""
    jupiter_base_url: str = ""
    dry_run: bool = True
    jup_cli_path: str = "jup"
    jup_cli_json_flag: str = "-f json"
    key_name: str = ""
    input_collateral: str = "USDC"
    receive_token: str = "USDC"
    slippage_bps: int = 200
    trade_log_path: Path = PROJECT_ROOT / "data" / "trades.csv"
    state_path: Path = PROJECT_ROOT / "data" / "state.json"

    @classmethod
    def from_env(cls, market_name: str = "SOL") -> "ExecutionConfig":
        market_key = market_name.lower()
        return cls(
            jupiter_api_key=os.getenv("JUPITER_API_KEY", ""),
            jupiter_base_url=os.getenv("JUPITER_BASE_URL", ""),
            dry_run=_env_bool("JUPITER_DRY_RUN", True),
            jup_cli_path=os.getenv("JUPITER_CLI_PATH", "jup"),
            key_name=os.getenv("JUPITER_KEY_NAME", ""),
            input_collateral=os.getenv("JUPITER_INPUT_COLLATERAL", "USDC"),
            receive_token=os.getenv("JUPITER_RECEIVE_TOKEN", "USDC"),
            slippage_bps=_env_int("JUPITER_SLIPPAGE_BPS", 200),
            trade_log_path=_resolve_project_path(os.getenv("TRADER_TRADE_LOG_PATH", f"data/{market_key}_trades.csv")),
            state_path=_resolve_project_path(os.getenv("TRADER_STATE_PATH", f"data/{market_key}_state.json")),
        )


@dataclass(frozen=True)
class AppConfig:
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig

    @classmethod
    def from_env(cls, market_name: str | None = None, markets_path: Path = DEFAULT_MARKETS_PATH) -> "AppConfig":
        load_env_file()
        market_config = load_market_config(market_name, markets_path)
        return cls(
            strategy=StrategyConfig.from_env(market_config),
            risk=RiskConfig.from_env(),
            execution=ExecutionConfig.from_env(market_config.name),
        )
