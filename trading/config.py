from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
class StrategyConfig:
    asset: str = "SOL"
    price_mint: str = WRAPPED_SOL_MINT
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
    def from_env(cls) -> "StrategyConfig":
        return cls(candle_minutes=_env_int("TRADER_CANDLE_MINUTES", 30))


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
    def from_env(cls) -> "ExecutionConfig":
        return cls(
            jupiter_api_key=os.getenv("JUPITER_API_KEY", ""),
            jupiter_base_url=os.getenv("JUPITER_BASE_URL", ""),
            dry_run=_env_bool("JUPITER_DRY_RUN", True),
            jup_cli_path=os.getenv("JUPITER_CLI_PATH", "jup"),
            key_name=os.getenv("JUPITER_KEY_NAME", ""),
            input_collateral=os.getenv("JUPITER_INPUT_COLLATERAL", "USDC"),
            receive_token=os.getenv("JUPITER_RECEIVE_TOKEN", "USDC"),
            slippage_bps=_env_int("JUPITER_SLIPPAGE_BPS", 200),
        )


@dataclass(frozen=True)
class AppConfig:
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_env_file()
        return cls(
            strategy=StrategyConfig.from_env(),
            risk=RiskConfig.from_env(),
            execution=ExecutionConfig.from_env(),
        )
