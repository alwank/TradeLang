"""Sequential single-position cash ledger over completed, observed bars."""

import math
from collections import Counter
from collections.abc import Callable

import numpy as np

from .curve import EquityCurve
from .data import instant, prepare_window, timeframe_label
from .decision import DecisionLog
from .evaluator import Evaluator
from .model import PRICE, UNITS, Problem
from .order_sizing import stop_size
from .portfolio_book import PortfolioLane, PortfolioPhase, PortfolioStep
from .position_ledger import LotStep, PositionLedger
from .session_clock import DAY_US
from .short_margin import liquidation_price, short_sale

ARTIFACT_SCHEMA_VERSION = 2
SEMANTICS_VERSION = "1.1.0"
SEMANTICS_V2 = "2.0.0"
SEMANTICS_V3 = "3.0.0"
SEMANTICS_V4 = "4.0.0"
SEMANTICS_V5 = "5.0.0"
SEMANTICS_V6 = "6.0.0"
SEMANTICS_V7 = "7.0.0"
SEMANTICS_V8 = "8.0.0"


def semantics_version(version):
    if version == 1:
        return SEMANTICS_VERSION
    if version == 2:
        return SEMANTICS_V2
    if version == 3:
        return SEMANTICS_V3
    if version == 4:
        return SEMANTICS_V4
    if version == 5:
        return SEMANTICS_V5
    if version == 6:
        return SEMANTICS_V6
    if version == 7:
        return SEMANTICS_V7
    if version == 8:
        return SEMANTICS_V8
    raise ValueError("Unknown language version")


def purchase(budget, reference, fee, slip, *, lot=None):
    price = reference * (1 + slip)
    q = budget / (price * (1 + fee))
    if lot:
        q = lot.floor(q)
    for _ in range(5):
        gross = q * price
        cost = gross * fee
        if 0 < q and math.isfinite(price) and 0 < gross + cost <= budget:
            return q, price, cost
        q = math.nextafter(q, 0)
        if lot:
            q = lot.floor(q)
    if lot:
        raise ArithmeticError("invalid_lot_quantity")
    raise ArithmeticError("Invalid entry debit")


def metrics(
    equities,
    trades,
    costs,
    exposure,
    seconds,
    duration,
    gapped,
    *,
    unavailable=None,
    session_based=False,
    can_be_insolvent=False,
):
    eq = np.asarray(equities)
    reasons = {} if unavailable is None else unavailable
    sharpe = None
    if session_based:
        reasons["sharpe"] = "session_intervals"
    elif can_be_insolvent and (eq <= 0).any():
        reasons["sharpe"] = "nonpositive_equity"
    elif len(eq) > 2 and duration >= 86400 and not gapped:
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            returns = eq[1:] / eq[:-1] - 1
            if not np.isfinite(returns).all():
                reasons["sharpe"] = "numeric_range"
            else:
                volatility = float(np.std(returns, ddof=1))
                if not math.isfinite(volatility):
                    returns = returns / np.max(np.abs(returns))
                    volatility = float(np.std(returns, ddof=1))
                if volatility:
                    sharpe = (
                        float(np.mean(returns))
                        / volatility
                        * math.sqrt(31557600 / seconds)
                    )
                    if not math.isfinite(sharpe):
                        sharpe = None
                        reasons["sharpe"] = "numeric_range"
    try:
        cagr = (
            (float(eq[-1]) / float(eq[0])) ** (31557600 / duration) - 1
            if duration >= 86400 and eq[-1] > 0
            else None
        )
    except OverflowError:
        cagr = None
        reasons["cagr"] = "numeric_range"
    if cagr is not None and not math.isfinite(cagr):
        cagr = None
        reasons["cagr"] = "numeric_range"
    if can_be_insolvent and eq[-1] <= 0:
        reasons["cagr"] = "nonpositive_equity"
    wins = [x["net_pnl"] for x in trades if x["net_pnl"] > 0]
    losses = [x["net_pnl"] for x in trades if x["net_pnl"] < 0]
    profit_factor = None
    profit_factor_status = "no_losses" if trades else "no_closed_trades"
    if losses:
        gain, loss = sum(wins), -sum(losses)
        if not math.isfinite(gain) or not math.isfinite(loss):
            scale = max(-min(losses), max(wins, default=0))
            gain = math.fsum(value / scale for value in wins)
            loss = math.fsum(-value / scale for value in losses)
        if loss:
            profit_factor = gain / loss
        if profit_factor is None or not math.isfinite(profit_factor):
            profit_factor = None
            profit_factor_status = "numeric_range"
        else:
            profit_factor_status = "finite"
    return dict(
        total_return=float(eq[-1] / eq[0]) - 1,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=float(-np.min(eq / np.maximum.accumulate(eq) - 1)),
        closed_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(trades) - len(wins) - len(losses),
        win_rate=len(wins) / len(trades) if trades else None,
        profit_factor=profit_factor,
        profit_factor_status=profit_factor_status,
        exposure_fraction=exposure / (len(eq) - 1),
        total_fees=costs["total_fees"],
        total_slippage_cost=costs["total_slippage_cost"],
    )


def costs():
    return dict.fromkeys(
        (
            "entry_fees",
            "exit_fees",
            "total_fees",
            "entry_slippage_cost",
            "exit_slippage_cost",
            "total_slippage_cost",
        ),
        0.0,
    )


def charge(c, side, fee, slippage):
    c[side + "_fees"] += fee
    c[side + "_slippage_cost"] += slippage
    c["total_fees"] += fee
    c["total_slippage_cost"] += slippage


def execute(s, d, *, profile=None, feeds=None):
    return execute_prepared(s, d, prepare_window(s, d, profile, feeds=feeds))


def execute_prepared(
    s,
    d,
    prepared,
    *,
    progress: Callable[[int, int], None] | None = None,
    decisions: DecisionLog | None = None,
):
    steps = execution_steps(s, d, prepared, progress=progress, decisions=decisions)
    try:
        next(steps)
    except StopIteration as result:
        return result.value
    raise AssertionError("Single-market execution yielded a portfolio step")


def execution_steps(
    s,
    d,
    prepared,
    *,
    progress: Callable[[int, int], None] | None = None,
    decisions: DecisionLog | None = None,
    lane: PortfolioLane | None = None,
):
    """Run one market, yielding synchronization points when it shares a book."""
    first, j, last = prepared.first, prepared.first_signal, prepared.last
    bar_seconds = prepared.timeframe_seconds
    dt = bar_seconds * 1000000
    total = last - first + 1
    if progress is not None:
        progress(0, total)
    ev = Evaluator(s, d, last, profiles=prepared.profiles, feeds=prepared.feeds)
    for e in s.roots():
        if e and not e.account:
            ev.evaluate(e)
    entry = ev.array(ev.evaluate(s.entry))
    exit_signal = ev.array(ev.evaluate(s.exit)) if s.exit is not None else None
    scale_signal = (
        ev.array(ev.evaluate(s.scale.condition)) if s.scale is not None else None
    )
    max_order_age = (s.order_max_age_seconds or 0) * 1_000_000
    manages_quantity = s.manages_quantity or lane is not None
    short_margin = s.short_margin
    short = short_margin is not None
    entry_side, exit_side = ("short", "cover") if short else ("buy", "sell")
    lot = LotStep(s.quantity_step) if s.quantity_step is not None else None
    cfg = s.config
    f = cfg.fee_rate
    slip = cfg.slippage_rate
    cash = bcash = peak = bpeak = lane.book.cash if lane is not None else cfg.capital
    q = bq = 0.0
    trades = []
    events: list[dict] = []
    curve = EquityCurve(d, first, last, dt) if lane is None else None
    warnings = list(s.warnings)
    count: Counter[str] = Counter()
    cost = costs()
    bcost = costs()
    pos: dict | None = None
    ledger: PositionLedger | None = None
    fill_sequence = 0
    id_prefix = f"{lane.name}:" if lane is not None else ""
    pending: dict | None = None
    pending_trail: dict | None = None
    i = first
    phase = 1
    open_at = instant(d.times[i])
    close_us = 0
    session_closes = d.session_rows.close if d.session_rows is not None else None
    split_factors = d.split_factors
    last_borrow_us = 0
    borrow_total = 0.0
    liquidations = 0

    warning_counts: Counter[str] = Counter()

    def event(kind, reason, **kwargs):
        seq = len(events) + 1
        precision = "close" if phase >= 6 else "bar" if phase == 5 else "open"
        row = dict(
            sequence=seq,
            event_id=f"E{seq:08}",
            bar_index=i,
            bar_open_at=open_at,
            observed_at=instant(close_us)
            if precision == "close" or (lane is not None and precision == "bar")
            else open_at,
            time_precision=precision,
            phase=phase,
            kind=kind,
            reason=reason,
            order_id=None,
            trade_id=None,
            fill_id=None,
            linked_event_id=None,
            side=None,
            reference_price=None,
            fill_price=None,
            quantity=None,
            fee=None,
            cash_delta=0.0,
            cash_after=cash,
            quantity_after=q,
            protection=None,
            trace=None,
            diagnostic_code=None,
        )
        if split_factors is not None:
            row["split_factor"] = float(split_factors[i])
        row.update(kwargs)
        if lane is not None:
            lane.record(row, reserved_for_short())
        events.append(row)
        if kind == "warning":
            warning_counts[row["diagnostic_code"]] += 1
        if kind == "fill":
            if d.values[i, 4] == 0:
                event(
                    "warning",
                    "zero_volume_fill",
                    diagnostic_code="W_ZERO_VOLUME_FILL",
                    linked_event_id=row["event_id"],
                )
            if not d.values[i, 2] <= row["fill_price"] <= d.values[i, 1]:
                event(
                    "warning",
                    "outside_candle_range",
                    diagnostic_code="W_FILL_OUTSIDE_RANGE",
                    linked_event_id=row["event_id"],
                )
        return row["event_id"]

    def trace(expr, root, idx):
        operands = []

        def visit(node, path, index):
            if node.type.kind != "record" and not node.account:
                v = ev.value(node, index)
                unit = next(
                    (k for k, u in UNITS.items() if u == node.type.unit),
                    str(node.type.unit),
                )
                operands.append(
                    dict(
                        node_id=path,
                        value=v,
                        unit=unit if node.type.kind == "numeric" else "boolean",
                        valid=v is not None,
                    )
                )
            child_index = (
                ev.aligned_row(node.value, index) if node.op == "align" else index
            )
            for key, child in node.children():
                visit(child, path + "." + key, child_index)

        visit(expr, root, idx)
        return dict(
            root_node_id=root, value=True, invalid_reason=None, operands=operands
        )

    def mark(price, exposed=False):
        nonlocal peak, bpeak
        assert curve is not None
        equity = cash + q * (price or 0)
        bequity = bcash + bq * (price or 0)
        cumulative_return = equity / cfg.capital - 1
        if (cash < 0 and not short) or not all(
            map(math.isfinite, (equity, bequity, cumulative_return))
        ):
            raise Problem("E_NUMERIC_EXECUTION", "Nonfinite or negative ledger")
        peak = max(peak, equity)
        bpeak = max(bpeak, bequity)
        curve.record(
            cash,
            q,
            equity,
            peak,
            equity / peak - 1,
            cumulative_return,
            bcash,
            bq,
            bequity,
            bpeak,
            bequity / bpeak - 1,
            exposed=exposed,
        )

    def next_fill_id():
        nonlocal fill_sequence
        fill_sequence += 1
        return f"{id_prefix}F{fill_sequence:08}"

    def reserved_for_short():
        if short_margin is None or ledger is None:
            return 0.0
        reserved = ledger.gross_basis * short_margin.initial_rate + ledger.gross_basis
        # Portfolio shorts use position collateral for maintenance. Accrued
        # borrowing consumes that collateral as well as the shared cash.
        return max(0.0, reserved - ledger.remaining_borrow_cost) if lane else reserved

    def margin_evidence():
        assert short_margin is not None
        proceeds = ledger.gross_basis if ledger is not None else 0.0
        initial_margin = proceeds * short_margin.initial_rate
        reserved = reserved_for_short()
        other_reserved = (
            math.fsum(
                item.reserved_cash for item in lane.book.lanes if item is not lane
            )
            if lane is not None
            else 0.0
        )
        available = cash - (reserved + other_reserved)
        if not math.isfinite(available):
            raise Problem("E_NUMERIC_EXECUTION", "Nonfinite available collateral")
        return dict(
            restricted_proceeds=proceeds,
            initial_margin=initial_margin,
            reserved_cash=reserved,
            available_cash=available,
        )

    def accrue_borrow(at):
        nonlocal cash, last_borrow_us, borrow_total
        assert short_margin is not None and ledger is not None and pos is not None
        elapsed = at - last_borrow_us
        last_borrow_us = at
        if not elapsed or not short_margin.borrow_rate_per_day:
            return
        fee = ledger.gross_basis * (
            short_margin.borrow_rate_per_day * (elapsed / DAY_US)
        )
        if not all(map(math.isfinite, (fee, cash - fee, borrow_total + fee))):
            raise Problem("E_NUMERIC_EXECUTION", "Nonfinite short borrow debit")
        ledger.charge_borrow(fee)
        cash -= fee
        borrow_total += fee
        event(
            "borrow_charged",
            "elapsed_time",
            trade_id=pos["trade_id"],
            cash_delta=-fee,
            borrow_cost=fee,
            elapsed_seconds=elapsed / 1_000_000,
            entry_notional=ledger.gross_basis,
            margin=margin_evidence(),
        )

    def maintenance_price():
        assert short_margin is not None
        collateral = reserved_for_short() if lane is not None else cash
        return liquidation_price(collateral, -q, f, slip, short_margin.maintenance_rate)

    def close_position(reference, reason, order=None, *, maintenance_trigger=None):
        nonlocal cash, q, pos, ledger, liquidations
        assert pos is not None
        qty = abs(q)
        if ledger is not None and order and "sale_mode" in order:
            try:
                qty = ledger.exit_quantity(order["sale_mode"], order["sale_requested"])
            except ArithmeticError as exc:
                event(
                    "exit_rejected",
                    str(exc),
                    side=exit_side,
                    order_id=order["id"],
                    trade_id=pos["trade_id"],
                    trace=order["trace"],
                )
                return False
        details = {"bar_index": i, "exit_reason": reason}
        price = reference * (1 + slip) if short else reference * (1 - slip)
        gross = qty * price
        fee = gross * f
        proceeds = gross + fee if short else gross - fee
        for label, amount in (
            ("price", price),
            ("gross notional", gross),
            ("proceeds", proceeds),
        ):
            if not math.isfinite(amount) or amount <= 0:
                raise Problem(
                    "E_NUMERIC_EXECUTION", f"Invalid exit {label}", details=details
                )
        if f > 0 and fee == 0:
            raise Problem("E_NUMERIC_EXECUTION", "Exit fee underflow", details=details)
        slippage = qty * abs(price - reference)
        cash_delta = -proceeds if short else proceeds
        cash_after = cash + cash_delta
        if not all(map(math.isfinite, (fee, slippage, cash_after))):
            raise Problem(
                "E_NUMERIC_EXECUTION", "Nonfinite exit accounting", details=details
            )
        ledger_data = {}
        if ledger is None:
            pl = qty * (price - pos["entry_price"])
            net = pl - pos["entry_fee"] - fee
            rate = net / (qty * pos["entry_price"] + pos["entry_fee"])
            if not all(map(math.isfinite, (pl, net, rate))):
                raise Problem(
                    "E_NUMERIC_EXECUTION", "Nonfinite exit accounting", details=details
                )
            q = 0.0
        else:
            try:
                leg = ledger.exit(qty, price, reference, fee, slippage)
            except ArithmeticError as exc:
                raise Problem("E_NUMERIC_EXECUTION", str(exc), details=details) from exc
            ledger_data = {"ledger": leg}
            q = leg["quantity_after"]
        charge(cost, "exit", fee, slippage)
        cash = cash_after
        rationale = order["trace"] if order else None
        if maintenance_trigger is not None:
            ledger_data["maintenance_trigger"] = (
                maintenance_trigger if math.isfinite(maintenance_trigger) else None
            )
            liquidations += 1
        event(
            "fill",
            "partial_exit" if q else reason,
            side=exit_side,
            trade_id=pos["trade_id"],
            order_id=order["id"] if order else None,
            fill_id=next_fill_id(),
            quantity=qty,
            reference_price=reference,
            fill_price=price,
            fee=fee,
            cash_delta=cash_delta,
            protection=pos["protection"],
            trace=rationale,
            **({"margin": margin_evidence()} if short else {}),
            **ledger_data,
        )
        if q:
            return False
        grouped_entry = {}
        exit_reference, exit_price, exit_fee, exit_slippage_cost = (
            reference,
            price,
            fee,
            slippage,
        )
        if ledger is not None:
            buys, sales = ledger.entries, ledger.exits
            grouped_entry = dict(
                quantity=buys.quantity,
                entry_reference=buys.reference_gross / buys.quantity,
                entry_price=buys.gross / buys.quantity,
                entry_fee=buys.fee,
                entry_slippage_cost=buys.slippage,
            )
            exit_reference, exit_price = (
                sales.reference_gross / sales.quantity,
                sales.gross / sales.quantity,
            )
            exit_fee, exit_slippage_cost = sales.fee, sales.slippage
            pl, net = ledger.realized_gross, ledger.realized_net
            entry_budget = (
                buys.gross * short_margin.initial_rate + buys.fee
                if short_margin is not None
                else buys.gross + buys.fee
            )
            rate = net / entry_budget
            if not all(map(math.isfinite, (exit_reference, exit_price, rate))):
                raise Problem(
                    "E_NUMERIC_EXECUTION", "Nonfinite position totals", details=details
                )
        trades.append(
            {
                **pos,
                **grouped_entry,
                "exit_signal_bar": order["bar"] if order else None,
                "exit_signal_at": order["at"] if order else None,
                "exit_bar": i,
                "exit_at": instant(close_us)
                if phase == 6 or (lane is not None and phase == 5)
                else open_at,
                "exit_time_precision": "close"
                if phase == 6
                else "bar"
                if phase == 5
                else "open",
                "exit_reference": exit_reference,
                "exit_price": exit_price,
                "exit_fee": exit_fee,
                "exit_slippage_cost": exit_slippage_cost,
                "gross_pnl": pl,
                "net_pnl": net,
                "return_fraction": rate,
                "bars_held": i - pos["entry_bar"] + 1,
                "exit_reason": reason,
                "exit_rationale": rationale,
                **(
                    dict(
                        borrow_cost=ledger.borrow_cost,
                        initial_collateral=ledger.entries.gross
                        * short_margin.initial_rate,
                    )
                    if short_margin is not None and ledger is not None
                    else {}
                ),
            }
        )
        pos = None
        ledger = None
        return True

    if lane is None:
        mark(None)
    for i in range(first, last + 1):
        event_start = len(events)
        if progress is not None and (i - first) % 256 == 0:
            progress(i - first, total)
        o, h, low, c, _ = map(float, d.values[i])
        open_at = instant(d.times[i])
        close_us = int(
            session_closes[i] if session_closes is not None else d.times[i] + dt
        )
        held = bool(pos)
        exited = False
        if lane is not None:
            yield PortfolioStep(int(d.times[i]), PortfolioPhase.REDUCE_AT_OPEN, o)
            cash = lane.book.cash
        elif i == j + 1:
            try:
                bq, bprice, bfee = purchase(bcash, o, f, slip)
            except ArithmeticError as exc:
                raise Problem("E_NUMERIC_EXECUTION", "Invalid benchmark fill") from exc
            bcash -= bq * bprice + bfee
            charge(bcost, "entry", bfee, bq * abs(bprice - o))
        phase = 1
        if pos:
            maintenance_trigger = None
            if short_margin is not None:
                accrue_borrow(int(d.times[i]))
            if pending_trail is not None:
                active_trail = {**pending_trail, "effective_open_at": open_at}
                pos["protection"] = {**pos["protection"], "stop": active_trail}
                event(
                    "trail_activated",
                    "next_observed_open",
                    trade_id=pos["trade_id"],
                    trail=active_trail,
                )
                pending_trail = None
            stop, target = (pos["protection"][k] for k in ("stop", "target"))
            if short_margin is not None:
                threshold = maintenance_price()
                reason = (
                    "liquidation_gap"
                    if o >= threshold
                    else "stop_gap"
                    if stop and o >= stop["trigger_price"]
                    else "target_gap"
                    if target and o <= target["trigger_price"]
                    else None
                )
                if reason == "liquidation_gap":
                    maintenance_trigger = threshold
            else:
                reason = (
                    "stop_gap"
                    if stop and o <= stop["trigger_price"]
                    else "target_gap"
                    if target and o >= target["trigger_price"]
                    else None
                )
            if reason:
                position_link = (
                    {"trade_id": pos["trade_id"]} if manages_quantity else {}
                )
                close_position(o, reason, maintenance_trigger=maintenance_trigger)
                exited = True
                if pending:
                    event(
                        "order_cancelled",
                        "maintenance_margin"
                        if reason == "liquidation_gap"
                        else "gap_protection",
                        order_id=pending["id"],
                        **position_link,
                    )
                pending = None
        if pending and max_order_age:
            age = int(d.times[i]) - pending["close_us"]
            if age >= max_order_age:
                phase = 2 if pending["side"] == exit_side else 3
                event(
                    "order_expired_stale",
                    "order_age_limit",
                    order_id=pending["id"],
                    side=pending["side"],
                    linked_event_id=pending["signal_event_id"],
                    trace=pending["trace"],
                    age_seconds=age / 1_000_000,
                    max_age_seconds=s.order_max_age_seconds,
                    **(
                        {"trade_id": pos["trade_id"]}
                        if pos and manages_quantity
                        else {}
                    ),
                )
                count["expired_orders"] += 1
                pending = None
        if pending and pending["side"] == exit_side:
            phase = 2
            exited = close_position(o, "signal_exit", pending)
            pending = None
        if lane is not None:
            yield PortfolioStep(int(d.times[i]), PortfolioPhase.COMMIT_AT_OPEN, o)
            cash = lane.book.cash
        if pending:
            if pending["side"] == "add":
                phase = 3
                assert s.scale is not None and pos is not None and ledger is not None
                sizing = s.scale.sizing
                equity = (
                    (lane.book.equity if lane is not None else cash + q * o)
                    if sizing.account
                    else None
                )
                available = lane.book.available_cash if lane is not None else cash
                value = ev.value(sizing, pending["bar"], equity)
                budget = (
                    value
                    if s.scale.fixed
                    else (value * available if value is not None else None)
                )
                try:
                    if lane is not None and budget is not None and budget > available:
                        raise ArithmeticError("insufficient_cash")
                    if (
                        budget is None
                        or not 0 < budget <= available
                        or not s.scale.fixed
                        and not 0 < value <= 1
                    ):
                        raise ArithmeticError("invalid_add_budget")
                    qty, price, fee = purchase(budget, o, f, slip, lot=lot)
                    if f and fee == 0:
                        raise ArithmeticError("entry_fee_underflow")
                    amount = qty * abs(price - o)
                    leg = ledger.enter(qty, price, o, fee, amount)
                except ArithmeticError as exc:
                    event(
                        "add_rejected",
                        str(exc),
                        side="add",
                        order_id=pending["id"],
                        trade_id=pos["trade_id"],
                        trace=pending["trace"],
                    )
                else:
                    debit = qty * price + fee
                    cash -= debit
                    q = ledger.quantity
                    charge(cost, "entry", fee, amount)
                    event(
                        "fill",
                        "scale_in",
                        side="buy",
                        order_id=pending["id"],
                        trade_id=pos["trade_id"],
                        fill_id=next_fill_id(),
                        reference_price=o,
                        fill_price=price,
                        quantity=qty,
                        fee=fee,
                        cash_delta=-debit,
                        protection=pos["protection"],
                        trace={
                            **pending["trace"],
                            "add_budget": budget,
                            "sizing_value": value,
                        },
                        ledger=leg,
                    )
            else:
                phase = 3
                equity = lane.book.equity if lane is not None else cash
                available = lane.book.available_cash if lane is not None else cash
                value = ev.value(s.sizing, pending["bar"], equity)
                budget = (
                    value if s.fixed else value * equity if value is not None else None
                )
                if decisions is not None:
                    decisions.entry(
                        i,
                        pending["bar"],
                        cash,
                        value,
                        budget,
                        equity=equity if lane is not None else None,
                    )
                entry_trace = pending["trace"]
                try:
                    if lane is not None:
                        entry_trace = {
                            **entry_trace,
                            "capital": dict(
                                available_cash=available,
                                equity=equity,
                                requested_budget=budget,
                                open_positions=lane.book.open_positions,
                                max_positions=lane.book.max_positions,
                            ),
                        }
                        if lane.book.open_positions >= lane.book.max_positions:
                            raise ArithmeticError("portfolio_position_limit")
                        if available <= 0 or (
                            not s.stop_risk
                            and budget is not None
                            and budget > available
                        ):
                            raise ArithmeticError("insufficient_cash")
                    if (
                        budget is None
                        or not 0 < budget
                        or (lane is None and budget > cash)
                    ):
                        raise ArithmeticError(
                            "invalid_risk_budget" if s.stop_risk else "invalid_budget"
                        )
                    if s.stop_risk:
                        allocation = (
                            ev.value(s.allocation_cap, pending["bar"], equity)
                            if s.allocation_cap is not None
                            else 1.0
                        )
                        if allocation is None or not 0 < allocation <= 1:
                            raise ArithmeticError("invalid_allocation_cap")
                        if value is None or not 0 < value <= 1:
                            raise ArithmeticError("invalid_risk_budget")
                        price = o * (1 + slip)
                    elif short_margin is not None:
                        qty, price, fee = short_sale(
                            budget, o, f, slip, short_margin.initial_rate, lot
                        )
                    else:
                        qty, price, fee = purchase(budget, o, f, slip, lot=lot)
                    protection = {}
                    for key, expr in (("stop", s.stop), ("target", s.target)):
                        anchor = None
                        if expr:
                            v = pending[key]
                            dist = v if expr.type.unit == PRICE else v * price
                            below = (key == "stop") != short
                            level = price - dist if below else price + dist
                            if not (
                                math.isfinite(level)
                                and level > 0
                                and (level < price if below else level > price)
                            ):
                                raise ArithmeticError("invalid_protection")
                            anchor = dict(
                                node_id=f"risk.{key}.expression",
                                sampled_bar=pending["bar"],
                                sampled_at=pending["at"],
                                expression_value=v,
                                unit="price" if expr.type.unit == PRICE else "ratio",
                                entry_anchor=price,
                                distance=dist,
                                trigger_price=level,
                            )
                        protection[key] = anchor
                    if s.stop_risk:
                        stop_anchor = protection["stop"]
                        assert stop_anchor is not None
                        qty, fee, sized = stop_size(
                            available,
                            value,
                            allocation,
                            o,
                            price,
                            stop_anchor["trigger_price"],
                            f,
                            slip,
                            lot=lot,
                            equity=equity if lane is not None else None,
                        )
                        entry_trace = {**entry_trace, "risk_sizing": sized}
                    amount = qty * abs(price - o)
                    initial_ledger = (
                        PositionLedger(lot, is_short=short)
                        if manages_quantity
                        else None
                    )
                    if initial_ledger is not None and f and fee == 0:
                        raise ArithmeticError("entry_fee_underflow")
                    cash_delta = qty * price - fee if short else -(qty * price + fee)
                    if short and not math.isfinite(cash + cash_delta):
                        raise ArithmeticError("nonfinite_short_sale_credit")
                    ledger_data = (
                        {"ledger": initial_ledger.enter(qty, price, o, fee, amount)}
                        if initial_ledger is not None
                        else {}
                    )
                except ArithmeticError as exc:
                    event(
                        "entry_rejected",
                        str(exc),
                        order_id=pending["id"],
                        trace=entry_trace if lane is not None else pending["trace"],
                    )
                    count["entry_rejections"] += 1
                else:
                    cash += cash_delta
                    q = -qty if short else qty
                    held = True
                    ledger = initial_ledger
                    fill_id = next_fill_id()
                    if ledger is not None:
                        ledger.opened_fill_id = fill_id
                        q = -ledger.quantity if short else ledger.quantity
                    if short:
                        last_borrow_us = int(d.times[i])
                    charge(cost, "entry", fee, amount)
                    pos = dict(
                        trade_id=f"{id_prefix}T{len(trades) + 1:06}",
                        direction="short" if short else "long",
                        entry_signal_bar=pending["bar"],
                        entry_signal_at=pending["at"],
                        entry_bar=i,
                        entry_at=open_at,
                        entry_reference=o,
                        entry_price=price,
                        quantity=q,
                        entry_fee=fee,
                        entry_slippage_cost=amount,
                        protection=protection,
                        entry_rationale=entry_trace,
                    )
                    event(
                        "fill",
                        "entry",
                        order_id=pending["id"],
                        trade_id=pos["trade_id"],
                        fill_id=fill_id,
                        side=entry_side,
                        reference_price=o,
                        fill_price=price,
                        quantity=qty,
                        fee=fee,
                        cash_delta=cash_delta,
                        protection=protection,
                        trace=entry_trace,
                        **({"margin": margin_evidence()} if short else {}),
                        **ledger_data,
                    )
                    phase = 4
                    stop = protection["stop"]
                    threshold = maintenance_price() if short else math.inf
                    if o >= threshold:
                        close_position(
                            o, "liquidation_entry_open", maintenance_trigger=threshold
                        )
                        exited = True
                    elif stop and (
                        o >= stop["trigger_price"]
                        if short
                        else o <= stop["trigger_price"]
                    ):
                        close_position(o, "stop_entry_open")
                        exited = True
            pending = None
        if lane is not None:
            yield PortfolioStep(close_us, PortfolioPhase.CLOSE, c)
            cash = lane.book.cash
        phase = 5
        if pos:
            stop, target = (pos["protection"][k] for k in ("stop", "target"))
            if short_margin is not None:
                threshold = maintenance_price()
                st = stop and h >= stop["trigger_price"]
                tg = target and low <= target["trigger_price"]
                liquidates = h >= threshold and (
                    not st or threshold <= stop["trigger_price"]
                )
            else:
                st = stop and low <= stop["trigger_price"]
                tg = target and h >= target["trigger_price"]
                liquidates = False
            if liquidates:
                close_position(
                    threshold, "liquidation_touch", maintenance_trigger=threshold
                )
                exited = True
            elif st or tg:
                if st and tg:
                    count["dual_touches"] += 1
                    event(
                        "warning",
                        "both_levels_touched",
                        diagnostic_code="W_DUAL_TOUCH",
                        trade_id=pos["trade_id"],
                    )
                close_position(
                    (stop if st else target)["trigger_price"],
                    "stop_dual_touch"
                    if st and tg
                    else "stop_touch"
                    if st
                    else "target_touch",
                )
                exited = True
        phase = 6
        if short_margin is not None and pos:
            accrue_borrow(close_us)
            threshold = maintenance_price()
            if c >= threshold:
                close_position(c, "liquidation_close", maintenance_trigger=threshold)
                exited = True
        if lane is None:
            mark(c, held)
        if i < j or exited:
            if decisions is not None:
                decisions.record(
                    i, 0 if i < j else 1, bool(pos), 0, 0, event_start, len(events)
                )
            continue
        phase = 7
        holding_closes = i - pos["entry_bar"] + 1 if pos else 0
        if pos and s.trail is not None and i < last:
            value = ev.value(s.trail, i)
            if value is not None and value > 0:
                dist = value if s.trail.type.unit == PRICE else value * c
                level = c + dist if short else c - dist
                previous = pos["protection"]["stop"]["trigger_price"]
                tightens = c < level < previous if short else previous < level < c
                if tightens:
                    pending_trail = dict(
                        node_id="risk.trail.expression",
                        sampled_bar=i,
                        sampled_at=instant(close_us),
                        expression_value=value,
                        unit="price" if s.trail.type.unit == PRICE else "ratio",
                        close_anchor=c,
                        distance=dist,
                        trigger_price=level,
                        previous_trigger_price=previous,
                    )
                    event(
                        "trail_queued",
                        "lower_stop" if short else "raise_stop",
                        trade_id=pos["trade_id"],
                        trail=pending_trail,
                    )
        selected = None
        if exit_signal is not None:
            exit_value = exit_signal[i]
        else:
            exit_value = 0.0
            for index, rule in enumerate(s.exit_rules):
                verdict = rule.predicate(
                    lambda expression: ev.value(expression, i), holding_closes
                )
                if verdict is True:
                    selected = index, rule
                    exit_value = 1.0
                    break
                if verdict is None:
                    exit_value = np.nan
        if entry[i] == 1 and (pos or exit_value == 1):
            event(
                "signal",
                "entry_ignored_holding" if pos else "exit_priority",
                side=entry_side,
            )
        side = (
            exit_side
            if pos and exit_value == 1
            else "add"
            if pos and scale_signal is not None and scale_signal[i] == 1
            else entry_side
            if not pos and exit_value != 1 and entry[i] == 1
            else None
        )
        if side is None:
            if decisions is not None:
                decisions.record(
                    i,
                    2,
                    bool(pos),
                    entry[i],
                    exit_value,
                    event_start,
                    len(events),
                    holding_closes=holding_closes,
                )
            continue
        sale = None
        if side == exit_side and selected is not None:
            index, rule = selected
            root = f"exit.rules.{index}"
            if rule.condition is not None:
                rationale = trace(rule.condition, f"{root}.condition", i)
            else:
                rationale = dict(
                    root_node_id=f"{root}.after_bars",
                    value=True,
                    invalid_reason=None,
                    operands=[],
                )
            rationale["exit_rule"] = dict(
                name=rule.name,
                order=index + 1,
                holding_closes=holding_closes,
                after_bars=rule.after_bars,
            )
            sale = rule.sale
        elif side == "add":
            rationale = trace(s.scale.condition, "scale.condition", i)
        else:
            rationale = trace(
                s.entry if side == entry_side else s.exit,
                ("entry" if side == entry_side else "exit") + ".condition",
                i,
            )
            if side == exit_side:
                sale = s.sale
        requested = ev.value(sale.expression, i) if sale is not None else None
        if sale is not None:
            rationale["sale_size"] = {"kind": sale.kind, "value": requested}
        count["signals"] += 1
        order_id = f"{id_prefix}O{count['signals']:08}"
        position_link = (
            {"trade_id": pos["trade_id"]} if pos and manages_quantity else {}
        )
        eid = event(
            "signal",
            side,
            side=side,
            order_id=order_id,
            trace=rationale,
            **position_link,
        )
        pending = dict(
            side=side,
            id=order_id,
            bar=i,
            at=instant(close_us),
            close_us=close_us,
            trace=rationale,
            signal_event_id=eid,
        )
        if sale is not None:
            if (
                requested is None
                or requested <= 0
                or (sale.kind == "fraction" and requested > 1)
            ):
                event(
                    "exit_rejected",
                    "invalid_exit_quantity",
                    side=exit_side,
                    order_id=order_id,
                    linked_event_id=eid,
                    trace=rationale,
                    **position_link,
                )
                pending = None
            else:
                pending.update(sale_mode=sale.kind, sale_requested=requested)
        elif side == entry_side:
            for key, expr in (
                ("stop", s.stop),
                ("target", s.target),
                ("sizing", s.sizing),
                ("allocation_cap", s.allocation_cap),
            ):
                if expr is None or expr.account:
                    continue
                v = ev.value(expr, i)
                bounded = key == "allocation_cap" or (key == "sizing" and s.stop_risk)
                if v is None or v <= 0 or (bounded and v > 1):
                    event(
                        "entry_rejected",
                        f"invalid_{key}",
                        order_id=order_id,
                        linked_event_id=eid,
                    )
                    count["entry_rejections"] += 1
                    pending = None
                    break
                pending[key] = v
        elif side == "add" and not s.scale.sizing.account:
            value = ev.value(s.scale.sizing, i)
            if value is None or value <= 0 or (not s.scale.fixed and value > 1):
                event(
                    "add_rejected",
                    "invalid_add_size",
                    side="add",
                    order_id=order_id,
                    linked_event_id=eid,
                    trace=rationale,
                    **position_link,
                )
                pending = None
        if pending:
            order_evidence = (
                {"trace": rationale}
                if ("exit_rule" in rationale or sale is not None or side == "add")
                else {}
            )
            if i == last:
                phase = 8
                event(
                    "order_expired_end",
                    "end_of_window",
                    order_id=order_id,
                    linked_event_id=eid,
                    **order_evidence,
                    **position_link,
                )
                count["expired_orders"] += 1
            else:
                event(
                    "order_queued",
                    side,
                    order_id=order_id,
                    linked_event_id=eid,
                    **order_evidence,
                    **position_link,
                )
        if decisions is not None:
            decisions.record(
                i,
                2,
                bool(pos),
                entry[i],
                exit_value,
                event_start,
                len(events),
                holding_closes=holding_closes,
            )
    if progress is not None:
        progress(total, total)
    duration = (close_us - int(d.times[first])) / 1e6
    missing_window_bars = d.missing_between(first, last)
    gaps = missing_window_bars > 0
    holding = None
    if pos:
        holding = {
            k: pos[k]
            for k in (
                "trade_id",
                "entry_bar",
                "entry_at",
                "quantity",
                "entry_reference",
                "entry_price",
                "entry_fee",
                "protection",
            )
        }
        holding.update(
            entry_fill_id=f"F{2 * len(trades) + 1:08}",
            mark_price=c,
            unrealized_gross=q * (c - pos["entry_price"]),
        )
        if ledger is not None:
            unrealized = abs(q) * c - ledger.gross_basis
            if short:
                unrealized = -unrealized
            holding.update(
                quantity=q,
                entry_fill_id=ledger.opened_fill_id,
                entry_price=ledger.gross_basis / abs(q),
                entry_fee=ledger.entry_fees,
                remaining_gross_basis=ledger.gross_basis,
                remaining_entry_fees=ledger.entry_fees,
                realized_gross_pnl=ledger.realized_gross,
                realized_net_pnl=ledger.realized_net,
                unrealized_gross=unrealized,
                unrealized_net=unrealized
                - ledger.entry_fees
                - ledger.remaining_borrow_cost,
            )
            if short:
                holding.update(
                    direction="short",
                    remaining_borrow_cost=ledger.remaining_borrow_cost,
                    margin=margin_evidence(),
                )
    for k in (
        "signals",
        "entry_rejections",
        "expired_orders",
        "dual_touches",
        "numeric_adjustments",
    ):
        count.setdefault(k, 0)
    if first < j:
        warning_counts["W_WARMUP_DELAY"] = j - first
    if missing_window_bars:
        warning_counts["W_MISSING_BARS"] = missing_window_bars
    if lane is not None:
        for trade in trades:
            trade["asset"] = lane.name
        return dict(
            trades=trades,
            open_position=holding,
            counts=dict(count),
            warnings=warnings,
            warning_counts=dict(warning_counts),
            costs={**cost, "total_borrow_cost": borrow_total},
            liquidations=liquidations,
        )
    assert curve is not None
    benchmark_unavailable: dict[str, str] = {}
    benchmark = dict(
        name="warmup_aligned_hold",
        entry_at=instant(d.times[j + 1]),
        quantity=bq,
        entry_reference=float(d.values[j + 1, 0]),
        entry_price=bprice,
        entry_fee=bfee,
        final_cash=bcash,
        final_equity=curve[-1]["benchmark_equity"],
        costs=bcost,
        terminal="mark_to_market",
        metrics=metrics(
            curve.column("benchmark_equity"),
            [],
            bcost,
            last - j,
            bar_seconds,
            duration,
            gaps,
            unavailable=benchmark_unavailable,
            session_based=session_closes is not None,
        ),
    )
    strategy_unavailable: dict[str, str] = {}
    strategy_metrics = metrics(
        curve.column("equity"),
        trades,
        cost,
        curve.exposed_bars(),
        bar_seconds,
        duration,
        gaps,
        unavailable=strategy_unavailable,
        session_based=session_closes is not None,
        can_be_insolvent=short,
    )
    for label, ms, unavailable in (
        ("strategy", strategy_metrics, strategy_unavailable),
        ("benchmark", benchmark["metrics"], benchmark_unavailable),
    ):
        for metric in ("sharpe", "cagr", "profit_factor", "win_rate"):
            if ms[metric] is None:
                reason = (
                    unavailable.get(metric)
                    or {
                        "profit_factor": ms["profit_factor_status"],
                        "win_rate": "no_closed_trades",
                        "sharpe": "irregular_intervals"
                        if gaps
                        else "short_window_or_zero_variance",
                        "cagr": "short_window_or_numeric_range",
                    }[metric]
                )
                warnings.append(
                    {
                        **Problem(
                            "W_METRIC_UNAVAILABLE",
                            f"{label} {metric} unavailable: {reason}",
                        ).diagnostic,
                        "severity": "info",
                        "details": {
                            "account": label,
                            "metric": metric,
                            "reason": reason,
                        },
                    }
                )
    for code, total in sorted(warning_counts.items()):
        warnings.append(
            {
                **Problem(code, f"{code}: {total} occurrences").diagnostic,
                "severity": "warning",
                "details": {"count": total},
            }
        )
    summary = dict(
        schema_version=1,
        quote_currency=cfg.currency,
        symbol=d.meta.symbol,
        timeframe=timeframe_label(bar_seconds),
        starting_capital=cfg.capital,
        final_equity=curve[-1]["equity"],
        final_cash=cash,
        open_position=holding,
        benchmark=benchmark,
        costs=cost,
        metrics=strategy_metrics,
        counts={**count, "unavailable_by_reason": ev.invalid},
        window=dict(
            first_open=curve[0]["timestamp"], last_close_at=curve[-1]["timestamp"]
        ),
        benchmark_entry_at=benchmark["entry_at"],
        warnings=warnings,
    )
    if manages_quantity:
        try:
            realized = math.fsum(
                [trade["net_pnl"] for trade in trades]
                + [ledger.realized_net if ledger else 0.0]
            )
        except OverflowError as exc:
            raise Problem(
                "E_NUMERIC_EXECUTION", "Nonfinite total realized profit"
            ) from exc
        summary["position_accounting"] = dict(
            realized_net_pnl=realized, fill_count=fill_sequence
        )
    if short:
        summary["costs"]["total_borrow_cost"] = borrow_total
        summary["short_accounting"] = dict(
            liquidations=liquidations,
            insolvent=summary["final_equity"] <= 0,
            **margin_evidence(),
        )
    return dict(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        summary=summary,
        trades=trades,
        equity=curve,
        events=events,
        diagnostics=warnings,
    )
