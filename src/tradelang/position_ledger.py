"""Weighted-average position accounting for quantity-changing orders."""

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import NotRequired, TypedDict


class FillLedger(TypedDict):
    leg: int
    quantity_before: float
    quantity_after: float
    remaining_gross_basis: float
    remaining_entry_fees: float
    gross_basis_released: float
    entry_fees_released: float
    realized_gross_pnl: float
    realized_net_pnl: float
    borrow_cost_released: NotRequired[float]


class LotStep:
    def __init__(self, step: float):
        self.value = Fraction(str(step))

    def floor(self, quantity: float) -> float:
        if not math.isfinite(quantity) or quantity <= 0:
            return 0.0
        lots = Fraction(str(quantity)) // self.value
        return float(lots * self.value)

    def change(self, held: float, change: float) -> float:
        # Executed quantities already lie on the grid. Recover individual lot
        # counts before adding or subtracting to keep the remainder on it.
        lots = round(Fraction(str(held)) / self.value) + round(
            Fraction(str(change)) / self.value
        )
        return float(lots * self.value)


@dataclass(frozen=True)
class FillTotals:
    quantity: float = 0.0
    gross: float = 0.0
    reference_gross: float = 0.0
    fee: float = 0.0
    slippage: float = 0.0

    def add(self, quantity, price, reference, fee, slippage):
        fields = (
            self.quantity + quantity,
            self.gross + quantity * price,
            self.reference_gross + quantity * reference,
            self.fee + fee,
            self.slippage + slippage,
        )
        if not all(map(math.isfinite, (*fields, fields[1] + fields[3]))):
            raise ArithmeticError("nonfinite_position_totals")
        return FillTotals(*fields)


@dataclass
class PositionLedger:
    step: LotStep | None
    is_short: bool = False
    quantity: float = 0.0
    gross_basis: float = 0.0
    entry_fees: float = 0.0
    realized_gross: float = 0.0
    realized_net: float = 0.0
    legs: int = 0
    opened_fill_id: str = ""
    entries: FillTotals = field(default_factory=FillTotals)
    exits: FillTotals = field(default_factory=FillTotals)
    borrow_cost: float = 0.0
    remaining_borrow_cost: float = 0.0

    def enter(self, quantity, price, reference, fee, slippage):
        previous = self.quantity
        qty = self.step.change(previous, quantity) if self.step else previous + quantity
        basis = self.gross_basis + quantity * price
        costs = self.entry_fees + fee
        if qty <= previous or not all(map(math.isfinite, (qty, basis, costs))):
            raise ArithmeticError("invalid_position_quantity")
        self.entries = self.entries.add(quantity, price, reference, fee, slippage)
        self.quantity, self.gross_basis, self.entry_fees = qty, basis, costs
        return self.evidence(previous, 0.0, 0.0, 0.0, 0.0)

    def exit_quantity(self, mode, requested):
        if (
            mode == "all"
            or mode == "fraction"
            and requested == 1
            or mode == "units"
            and requested == self.quantity
        ):
            return self.quantity
        quantity = self.quantity * requested if mode == "fraction" else requested
        if not 0 < quantity < self.quantity:
            raise ArithmeticError("invalid_sale_quantity")
        if self.step is not None:
            quantity = self.step.floor(quantity)
        if (
            not 0 < quantity < self.quantity
            or self.quantity - quantity == self.quantity
        ):
            raise ArithmeticError("invalid_sale_quantity")
        return quantity

    def charge_borrow(self, amount):
        total = self.borrow_cost + amount
        remaining = self.remaining_borrow_cost + amount
        if not math.isfinite(total):
            raise ArithmeticError("nonfinite_borrow_cost")
        self.borrow_cost, self.remaining_borrow_cost = total, remaining

    def exit(self, qty, price, reference, fee, slippage):
        previous = self.quantity
        full = qty == previous
        remaining = self.step.change(previous, -qty) if self.step else previous - qty
        if (not full and not 0 < remaining < previous) or (full and remaining != 0):
            raise ArithmeticError("invalid_position_quantity")
        if full:
            basis, entry_fees = self.gross_basis, self.entry_fees
            remaining_basis = remaining_fees = 0.0
        elif qty <= remaining:
            share = qty / previous
            basis, entry_fees = self.gross_basis * share, self.entry_fees * share
            remaining_basis, remaining_fees = (
                self.gross_basis - basis,
                self.entry_fees - entry_fees,
            )
        else:
            share = remaining / previous
            remaining_basis, remaining_fees = (
                self.gross_basis * share,
                self.entry_fees * share,
            )
            basis, entry_fees = (
                self.gross_basis - remaining_basis,
                self.entry_fees - remaining_fees,
            )
        borrow = 0.0
        if self.is_short:
            share = qty / previous
            borrow = self.remaining_borrow_cost * share
            if qty > remaining and not full:
                left = self.remaining_borrow_cost * (remaining / previous)
                borrow = self.remaining_borrow_cost - left
        gross_pnl = basis - qty * price if self.is_short else qty * price - basis
        net_pnl = gross_pnl - entry_fees - fee - borrow
        realized_gross = self.realized_gross + gross_pnl
        realized_net = self.realized_net + net_pnl
        if not all(map(math.isfinite, (realized_gross, realized_net))):
            raise ArithmeticError("nonfinite_position_profit")
        self.exits = self.exits.add(qty, price, reference, fee, slippage)
        self.quantity = remaining
        self.gross_basis, self.entry_fees = remaining_basis, remaining_fees
        self.realized_gross, self.realized_net = realized_gross, realized_net
        self.remaining_borrow_cost -= borrow
        leg = self.evidence(previous, basis, entry_fees, gross_pnl, net_pnl)
        if self.is_short:
            leg["borrow_cost_released"] = borrow
        return leg

    def evidence(self, previous, basis, entry_fees, gross_pnl, net_pnl) -> FillLedger:
        self.legs += 1
        return FillLedger(
            leg=self.legs,
            quantity_before=-previous if self.is_short and previous else previous,
            quantity_after=-self.quantity
            if self.is_short and self.quantity
            else self.quantity,
            remaining_gross_basis=self.gross_basis,
            remaining_entry_fees=self.entry_fees,
            gross_basis_released=basis,
            entry_fees_released=entry_fees,
            realized_gross_pnl=gross_pnl,
            realized_net_pnl=net_pnl,
        )
