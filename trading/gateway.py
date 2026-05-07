from __future__ import annotations

from typing import Any, Protocol

from trading.broker import Broker
from trading.domain import ExecutionReport, OrderIntent


class TradingGateway(Protocol):
    def execute(self, order: OrderIntent) -> ExecutionReport:
        raise NotImplementedError

    def positions(self) -> dict[str, Any]:
        raise NotImplementedError


class BrokerGateway:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    def execute(self, order: OrderIntent) -> ExecutionReport:
        return self.broker.execute(order)

    def positions(self) -> dict[str, Any]:
        return self.broker.positions()