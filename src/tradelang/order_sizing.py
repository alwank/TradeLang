"""Size a long using a finite stop-touch loss and fee-inclusive cash limits."""

import math
from typing import Literal, TypedDict

from .position_ledger import LotStep

Constraint = Literal["risk_budget", "cash", "allocation"]


class RiskSizingTrace(TypedDict):
    risk_fraction: float
    risk_budget: float
    allocation_fraction: float
    allocation_limit: float
    cash_available: float
    entry_open: float
    entry_fill_price: float
    stop_trigger_price: float
    modeled_stop_fill_price: float
    entry_debit_per_unit: float
    stop_proceeds_per_unit: float
    loss_per_unit: float
    quantity: float
    entry_debit: float
    modeled_loss: float
    binding_constraint: Constraint
    rounded_down: bool


def stop_size(
    cash: float,
    risk_fraction: float,
    allocation_fraction: float,
    reference: float,
    price: float,
    stop: float,
    fee: float,
    slip: float,
    *,
    lot: LotStep | None = None,
    equity: float | None = None,
) -> tuple[float, float, RiskSizingTrace]:
    sizing_equity = cash if equity is None else equity
    risk_budget = sizing_equity * risk_fraction
    allocation_limit = sizing_equity * allocation_fraction
    entry_unit_debit = price + price * fee
    stop_fill = stop * (1 - slip)
    stop_unit_proceeds = stop_fill - stop_fill * fee
    loss_per_unit = (price - stop_fill) + price * fee + stop_fill * fee
    if not all(
        math.isfinite(amount) and amount > 0
        for amount in (
            risk_budget,
            allocation_limit,
            entry_unit_debit,
            stop_unit_proceeds,
            loss_per_unit,
        )
    ):
        raise ArithmeticError("invalid_stop_risk")

    constraints: list[tuple[float, Constraint]] = [
        (risk_budget / loss_per_unit, "risk_budget"),
        (cash / entry_unit_debit, "cash"),
        (allocation_limit / entry_unit_debit, "allocation"),
    ]
    limit, constraint = min(constraints, key=lambda item: item[0])
    if not math.isfinite(limit):
        raise ArithmeticError("invalid_risk_quantity")
    quantity = lot.floor(limit) if lot else limit
    for _ in range(5):
        gross = quantity * price
        entry_fee = gross * fee
        debit = gross + entry_fee
        stop_gross = quantity * stop_fill
        stop_fee = stop_gross * fee
        # Guard both the per-unit calculation and the rounded ledger arithmetic.
        modeled_loss = max(
            quantity * loss_per_unit,
            quantity * (price - stop_fill) + entry_fee + stop_fee,
        )
        if not 0 < stop_gross - stop_fee or (fee > 0 and min(entry_fee, stop_fee) == 0):
            break
        if 0 < debit <= min(cash, allocation_limit) and 0 < modeled_loss <= risk_budget:
            trace = RiskSizingTrace(
                risk_fraction=risk_fraction,
                risk_budget=risk_budget,
                allocation_fraction=allocation_fraction,
                allocation_limit=allocation_limit,
                cash_available=cash,
                entry_open=reference,
                entry_fill_price=price,
                stop_trigger_price=stop,
                modeled_stop_fill_price=stop_fill,
                entry_debit_per_unit=entry_unit_debit,
                stop_proceeds_per_unit=stop_unit_proceeds,
                loss_per_unit=loss_per_unit,
                quantity=quantity,
                entry_debit=debit,
                modeled_loss=modeled_loss,
                binding_constraint=constraint,
                rounded_down=quantity < limit,
            )
            return quantity, entry_fee, trace
        quantity = math.nextafter(quantity, 0)
        if lot:
            quantity = lot.floor(quantity)
    raise ArithmeticError("invalid_risk_quantity")
