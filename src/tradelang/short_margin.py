"""Prices, initial collateral, and maintenance policy for a borrowed-asset short."""

import math


def short_sale(budget, reference, fee_rate, slippage, initial_rate, lot):
    price = reference * (1 - slippage)
    required_per_unit = price * (initial_rate + fee_rate)
    if not math.isfinite(required_per_unit) or required_per_unit <= 0:
        raise ArithmeticError("invalid_short_sale_price")
    quantity = budget / required_per_unit
    if lot is not None:
        quantity = lot.floor(quantity)
    for _ in range(5):
        proceeds = quantity * price
        collateral = proceeds * initial_rate
        fee = proceeds * fee_rate
        if (
            math.isfinite(proceeds + collateral)
            and 0 < collateral <= collateral + fee <= budget
            and (fee or not fee_rate)
        ):
            return quantity, price, fee
        quantity = math.nextafter(quantity, 0)
        if lot is not None:
            quantity = lot.floor(quantity)
    raise ArithmeticError("invalid_short_collateral")


def liquidation_price(cash, quantity, fee_rate, slippage, maintenance_rate):
    cover_multiplier = (1 + slippage) * (1 + fee_rate)
    return (cash / (cover_multiplier + maintenance_rate)) / quantity
