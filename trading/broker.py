from __future__ import annotations

import json
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from trading.config import ExecutionConfig
from trading.models import ExecutionReport, OrderIntent, SignalAction


class Broker(ABC):
    @abstractmethod
    def execute(self, order: OrderIntent) -> ExecutionReport:
        raise NotImplementedError

    def positions(self) -> dict[str, Any]:
        return {}


class DryRunBroker(Broker):
    def execute(self, order: OrderIntent) -> ExecutionReport:
        return ExecutionReport(
            accepted=True,
            dry_run=True,
            message=f"paper {order.action.value} accepted: {order.reason}",
            raw_response={"order": order.__dict__},
            position_id=order.position_id,
        )


class JupiterCliPerpsBroker(Broker):
    def __init__(self, execution_config: ExecutionConfig) -> None:
        self.execution_config = execution_config

    def execute(self, order: OrderIntent) -> ExecutionReport:
        if order.action == SignalAction.OPEN:
            return self._open(order)
        if order.action == SignalAction.CLOSE:
            return self._close(order)
        return ExecutionReport(False, self.execution_config.dry_run, "hold orders are not sent")

    def positions(self) -> dict[str, Any]:
        args = [self.execution_config.jup_cli_path, "perps", "positions"]
        self._append_key(args)
        self._append_json_flag(args)
        completed = self._run(args)
        return completed.raw_response or {"message": completed.message}

    def _open(self, order: OrderIntent) -> ExecutionReport:
        if order.side is None or order.stop_loss is None or order.take_profit is None:
            return ExecutionReport(False, self.execution_config.dry_run, "open order is missing side or TP/SL")
        args = [
            self.execution_config.jup_cli_path,
            "perps",
            "open",
            "--asset",
            order.asset,
            "--side",
            order.side.value,
            "--amount",
            f"{order.collateral_usd:.6f}",
            "--input",
            self.execution_config.input_collateral,
            "--leverage",
            f"{order.leverage:.4f}",
            "--tp",
            f"{order.take_profit:.6f}",
            "--sl",
            f"{order.stop_loss:.6f}",
            "--slippage",
            str(self.execution_config.slippage_bps),
        ]
        self._append_key(args)
        if self.execution_config.dry_run:
            args.append("--dry-run")
        self._append_json_flag(args)
        return self._run(args)

    def _close(self, order: OrderIntent) -> ExecutionReport:
        if not order.position_id:
            return ExecutionReport(False, self.execution_config.dry_run, "close order needs a position_id")
        args = [
            self.execution_config.jup_cli_path,
            "perps",
            "close",
            "--position",
            order.position_id,
            "--receive",
            self.execution_config.receive_token,
        ]
        self._append_key(args)
        if self.execution_config.dry_run:
            args.append("--dry-run")
        self._append_json_flag(args)
        return self._run(args)

    def _append_key(self, args: list[str]) -> None:
        if self.execution_config.key_name:
            args.extend(["--key", self.execution_config.key_name])

    def _append_json_flag(self, args: list[str]) -> None:
        if self.execution_config.jup_cli_json_flag:
            args.extend(shlex.split(self.execution_config.jup_cli_json_flag))

    def _run(self, args: list[str]) -> ExecutionReport:
        try:
            completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            return ExecutionReport(False, self.execution_config.dry_run, "Jupiter CLI not found; install @jup-ag/cli")
        except subprocess.TimeoutExpired:
            return ExecutionReport(False, self.execution_config.dry_run, "Jupiter CLI command timed out")

        parsed_stdout = self._parse_json(completed.stdout)
        accepted = completed.returncode == 0
        message = completed.stderr.strip() or completed.stdout.strip() or f"jup exited with {completed.returncode}"
        signature = ""
        position_id = ""
        if isinstance(parsed_stdout, dict):
            signature = str(parsed_stdout.get("signature") or "")
            position_id = str(parsed_stdout.get("positionPubkey") or parsed_stdout.get("position") or "")
        return ExecutionReport(
            accepted=accepted,
            dry_run=self.execution_config.dry_run,
            message=message,
            raw_response=parsed_stdout if isinstance(parsed_stdout, dict) else {"stdout": completed.stdout, "stderr": completed.stderr},
            signature=signature,
            position_id=position_id,
        )

    @staticmethod
    def _parse_json(raw_output: str) -> dict[str, Any] | list[Any] | None:
        stripped = raw_output.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
