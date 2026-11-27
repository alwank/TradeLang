"""Cash, observed marks, and order priority shared by a portfolio's assets."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from math import fsum, isfinite

from .data import instant
from .model import Problem


def ledger_total(values: Iterable[float]) -> float:
    try:
        total = fsum(values)
    except (OverflowError, ValueError) as error:
        raise Problem("E_NUMERIC_EXECUTION", "Nonfinite portfolio ledger total") from error
    if not isfinite(total):
        raise Problem("E_NUMERIC_EXECUTION", "Nonfinite portfolio ledger total")
    return total


class PortfolioPhase(IntEnum):
    CLOSE = 0
    REDUCE_AT_OPEN = 1
    COMMIT_AT_OPEN = 2


@dataclass(frozen=True, order=True)
class PortfolioStep:
    timestamp: int
    phase: PortfolioPhase
    price: float = field(compare=False)


@dataclass
class PortfolioBook:
    cash: float
    max_positions: int
    lanes: list["PortfolioLane"] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    @property
    def reserved_cash(self) -> float:
        return ledger_total(lane.reserved_cash for lane in self.lanes)

    @property
    def available_cash(self) -> float:
        return self.cash - self.reserved_cash

    @property
    def equity(self) -> float:
        return ledger_total([self.cash, *(lane.market_value for lane in self.lanes)])

    @property
    def open_positions(self) -> int:
        return sum(lane.quantity != 0 for lane in self.lanes)

    def attach(self, name: str) -> "PortfolioLane":
        lane = PortfolioLane(name, self)
        self.lanes.append(lane)
        return lane


@dataclass
class PortfolioLane:
    name: str
    book: PortfolioBook
    mark_price: float = 0.0
    timestamp: int | None = None
    quantity: float = 0.0
    reserved_cash: float = 0.0
    realized_net: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price

    def observe(self, step: PortfolioStep) -> None:
        self.mark_price, self.timestamp = step.price, step.timestamp

    def record(self, row: dict, reserved_cash: float) -> None:
        self.book.cash = row["cash_after"]
        self.quantity = row["quantity_after"]
        self.reserved_cash = reserved_cash
        sequence = len(self.book.events) + 1
        row.update(
            asset=self.name,
            sequence=sequence,
            event_id=f"E{sequence:08}",
        )
        if row["kind"] == "fill" and row.get("ledger"):
            self.realized_net += row["ledger"]["realized_net_pnl"]
            if not isfinite(self.realized_net):
                raise Problem("E_NUMERIC_EXECUTION", "Nonfinite asset realized profit")
        self.book.events.append(row)

    def mark(self) -> dict:
        return dict(
            asset=self.name,
            mark_at=instant(self.timestamp) if self.timestamp is not None else None,
            mark_price=self.mark_price if self.timestamp is not None else None,
            quantity=self.quantity,
            market_value=self.market_value,
            reserved_cash=self.reserved_cash,
            realized_net_pnl=self.realized_net,
        )
