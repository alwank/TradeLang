"""Sequential single-position cash ledger over completed, observed bars."""

import math
from collections import Counter

import numpy as np

from .curve import EquityCurve
from .data import instant, prepare_window, timeframe_label
from .evaluator import Evaluator
from .model import PRICE, UNITS, Problem

ARTIFACT_SCHEMA_VERSION = 2
SEMANTICS_VERSION = "1.1.0"


def purchase(budget, reference, fee, slip):
    price = reference * (1 + slip)
    q = budget / (price * (1 + fee))
    for _ in range(5):
        gross = q * price
        cost = gross * fee
        if 0 < q and math.isfinite(price) and 0 < gross + cost <= budget:
            return q, price, cost
        q = math.nextafter(q, 0)
    raise ArithmeticError("Invalid entry debit")


def metrics(equities, trades, costs, exposure, seconds, duration, gapped):
    eq = np.asarray(equities)
    returns = eq[1:] / eq[:-1] - 1
    vol = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0
    sharpe = (
        float(np.mean(returns)) / vol * math.sqrt(31557600 / seconds)
        if vol and duration >= 86400 and not gapped
        else None
    )
    try:
        cagr = (
            (float(eq[-1]) / float(eq[0])) ** (31557600 / duration) - 1
            if duration >= 86400 and eq[-1] > 0
            else None
        )
    except OverflowError:
        cagr = None
    wins = [x["net_pnl"] for x in trades if x["net_pnl"] > 0]
    losses = [x["net_pnl"] for x in trades if x["net_pnl"] < 0]
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
        profit_factor=sum(wins) / -sum(losses) if losses else None,
        profit_factor_status="finite"
        if losses
        else "no_losses"
        if trades
        else "no_closed_trades",
        exposure_fraction=exposure / len(returns),
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


def execute(s, d, *, profile=None):
    return execute_prepared(s, d, prepare_window(s, d, profile))


def execute_prepared(s, d, prepared):
    first, j, last = prepared.first, prepared.first_signal, prepared.last
    ev = Evaluator(s, d, last, profiles=prepared.profiles)
    for e in s.roots():
        if e and not e.account:
            ev.evaluate(e)
    entry = ev.array(ev.evaluate(s.entry))
    exit_signal = ev.array(ev.evaluate(s.exit))
    cfg = s.config
    f = cfg.fee_rate
    slip = cfg.slippage_rate
    cash = bcash = peak = bpeak = cfg.capital
    q = bq = 0.0
    trades = []
    events: list[dict] = []
    curve = EquityCurve(d, first, last, s.seconds * 1000000)
    warnings = list(s.warnings)
    count: Counter[str] = Counter()
    cost = costs()
    bcost = costs()
    pos: dict | None = None
    pending: dict | None = None
    dt = s.seconds * 1000000
    i = first
    phase = 1
    open_at = instant(d.times[i])

    warning_counts: Counter[str] = Counter()

    def event(kind, reason, **kwargs):
        seq = len(events) + 1
        precision = "close" if phase >= 6 else "bar" if phase == 5 else "open"
        row = dict(
            sequence=seq,
            event_id=f"E{seq:08}",
            bar_index=i,
            bar_open_at=open_at,
            observed_at=instant(d.times[i] + dt) if precision == "close" else open_at,
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
        row.update(kwargs)
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

        def visit(node, path):
            if node.type.kind != "record" and not node.account:
                v = ev.value(node, idx)
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
            keys = {
                "bool": [f"operands.{n}" for n in range(len(node.args))],
                "call": [f"arguments.{n}" for n in range(len(node.args))],
                "field": ["base"],
                "offset": ["base"],
                "unary": ["operand"],
            }.get(node.op, ["left", "right"])
            for child, key in zip(node.args, keys):
                visit(child, path + "." + key)

        visit(expr, root)
        return dict(
            root_node_id=root, value=True, invalid_reason=None, operands=operands
        )

    def mark(price, exposed=False):
        nonlocal peak, bpeak
        equity = cash + q * (price or 0)
        bequity = bcash + bq * (price or 0)
        cumulative_return = equity / cfg.capital - 1
        if cash < 0 or not all(
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

    def sell(reference, reason, order=None):
        nonlocal cash, q, pos
        assert pos is not None
        details = {"bar_index": i, "exit_reason": reason}
        price = reference * (1 - slip)
        gross = q * price
        fee = gross * f
        proceeds = gross - fee
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
        slippage = q * abs(price - reference)
        pl = q * (price - pos["entry_price"])
        net = pl - pos["entry_fee"] - fee
        rate = net / (q * pos["entry_price"] + pos["entry_fee"])
        cash_after = cash + proceeds
        if not all(map(math.isfinite, (fee, slippage, pl, net, rate, cash_after))):
            raise Problem(
                "E_NUMERIC_EXECUTION", "Nonfinite exit accounting", details=details
            )
        charge(cost, "exit", fee, slippage)
        cash = cash_after
        qty = q
        q = 0.0
        filltime = "bar" if phase == 5 else "open"
        trade = {
            **pos,
            "exit_signal_bar": order["bar"] if order else None,
            "exit_signal_at": order["at"] if order else None,
            "exit_bar": i,
            "exit_at": open_at,
            "exit_time_precision": filltime,
            "exit_reference": reference,
            "exit_price": price,
            "exit_fee": fee,
            "exit_slippage_cost": slippage,
            "gross_pnl": pl,
            "net_pnl": net,
            "return_fraction": rate,
            "bars_held": i - pos["entry_bar"] + 1,
            "exit_reason": reason,
            "exit_rationale": order["trace"] if order else None,
        }
        trades.append(trade)
        event(
            "fill",
            reason,
            side="sell",
            trade_id=pos["trade_id"],
            order_id=order["id"] if order else None,
            fill_id=f"F{2 * len(trades):08}",
            quantity=qty,
            reference_price=reference,
            fill_price=price,
            fee=fee,
            cash_delta=proceeds,
            protection=pos["protection"],
            trace=trade["exit_rationale"],
        )
        pos = None

    mark(None)
    for i in range(first, last + 1):
        o, h, low, c, _ = map(float, d.values[i])
        open_at = instant(d.times[i])
        held = bool(pos)
        exited = False
        if i == j + 1:
            try:
                bq, bprice, bfee = purchase(bcash, o, f, slip)
            except ArithmeticError as exc:
                raise Problem("E_NUMERIC_EXECUTION", "Invalid benchmark fill") from exc
            bcash -= bq * bprice + bfee
            charge(bcost, "entry", bfee, bq * abs(bprice - o))
        phase = 1
        if pos:
            stop, target = (pos["protection"][k] for k in ("stop", "target"))
            reason = (
                "stop_gap"
                if stop and o <= stop["trigger_price"]
                else "target_gap"
                if target and o >= target["trigger_price"]
                else None
            )
            if reason:
                sell(o, reason)
                exited = True
                if pending:
                    event("order_cancelled", "gap_protection", order_id=pending["id"])
                pending = None
        if pending:
            if pending["side"] == "sell":
                phase = 2
                sell(o, "signal_exit", pending)
                exited = True
            else:
                phase = 3
                value = ev.value(s.sizing, pending["bar"], cash)
                budget = (
                    value if s.fixed else value * cash if value is not None else None
                )
                try:
                    if budget is None or not 0 < budget <= cash:
                        raise ArithmeticError("invalid_budget")
                    qty, price, fee = purchase(budget, o, f, slip)
                    protection = {}
                    for key, expr in (("stop", s.stop), ("target", s.target)):
                        anchor = None
                        if expr:
                            v = pending[key]
                            dist = v if expr.type.unit == PRICE else v * price
                            level = price - dist if key == "stop" else price + dist
                            if not (
                                math.isfinite(level)
                                and level > 0
                                and (level < price if key == "stop" else level > price)
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
                except ArithmeticError as exc:
                    event(
                        "entry_rejected",
                        str(exc),
                        order_id=pending["id"],
                        trace=pending["trace"],
                    )
                    count["entry_rejections"] += 1
                else:
                    debit = qty * price + fee
                    cash -= debit
                    q = qty
                    held = True
                    amount = q * abs(price - o)
                    charge(cost, "entry", fee, amount)
                    pos = dict(
                        trade_id=f"T{len(trades) + 1:06}",
                        direction="long",
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
                        entry_rationale=pending["trace"],
                    )
                    event(
                        "fill",
                        "entry",
                        order_id=pending["id"],
                        trade_id=pos["trade_id"],
                        fill_id=f"F{2 * len(trades) + 1:08}",
                        side="buy",
                        reference_price=o,
                        fill_price=price,
                        quantity=q,
                        fee=fee,
                        cash_delta=-debit,
                        protection=protection,
                        trace=pending["trace"],
                    )
                    phase = 4
                    if protection["stop"] and o <= protection["stop"]["trigger_price"]:
                        sell(o, "stop_entry_open")
                        exited = True
            pending = None
        phase = 5
        if pos:
            stop, target = (pos["protection"][k] for k in ("stop", "target"))
            st = stop and low <= stop["trigger_price"]
            tg = target and h >= target["trigger_price"]
            if st or tg:
                if st and tg:
                    count["dual_touches"] += 1
                    event(
                        "warning",
                        "both_levels_touched",
                        diagnostic_code="W_DUAL_TOUCH",
                        trade_id=pos["trade_id"],
                    )
                sell(
                    (stop if st else target)["trigger_price"],
                    "stop_dual_touch"
                    if st and tg
                    else "stop_touch"
                    if st
                    else "target_touch",
                )
                exited = True
        phase = 6
        mark(c, held)
        if i < j or exited:
            continue
        phase = 7
        if entry[i] == 1 and (pos or exit_signal[i] == 1):
            event(
                "signal",
                "entry_ignored_holding" if pos else "exit_priority",
                side="buy",
            )
        side = (
            "sell"
            if pos and exit_signal[i] == 1
            else "buy"
            if not pos and exit_signal[i] != 1 and entry[i] == 1
            else None
        )
        if side is None:
            continue
        expr = s.entry if side == "buy" else s.exit
        rationale = trace(
            expr, ("entry" if side == "buy" else "exit") + ".condition", i
        )
        count["signals"] += 1
        order_id = f"O{count['signals']:08}"
        eid = event("signal", side, side=side, order_id=order_id, trace=rationale)
        pending = dict(
            side=side, id=order_id, bar=i, at=instant(d.times[i] + dt), trace=rationale
        )
        if side == "buy":
            for key, expr in (
                ("stop", s.stop),
                ("target", s.target),
                ("sizing", s.sizing),
            ):
                if expr is None or expr.account:
                    continue
                v = ev.value(expr, i)
                if v is None or v <= 0:
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
        if pending:
            if i == last:
                phase = 8
                event(
                    "order_expired_end",
                    "end_of_window",
                    order_id=order_id,
                    linked_event_id=eid,
                )
                count["expired_orders"] += 1
            else:
                event("order_queued", side, order_id=order_id, linked_event_id=eid)
    duration = (int(d.times[last] - d.times[first]) + dt) / 1e6
    gaps = duration != (last - first + 1) * s.seconds
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
            s.seconds,
            duration,
            gaps,
        ),
    )
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
    if d.missing:
        warning_counts["W_MISSING_BARS"] = d.missing
    strategy_metrics = metrics(
        curve.column("equity"),
        trades,
        cost,
        curve.exposed_bars(),
        s.seconds,
        duration,
        gaps,
    )
    for label, ms in (
        ("strategy", strategy_metrics),
        ("benchmark", benchmark["metrics"]),
    ):
        for metric in ("sharpe", "cagr", "profit_factor", "win_rate"):
            if ms[metric] is None:
                reason = {
                    "profit_factor": ms["profit_factor_status"],
                    "win_rate": "no_closed_trades",
                    "sharpe": "irregular_intervals"
                    if gaps
                    else "short_window_or_zero_variance",
                    "cagr": "short_window_or_numeric_range",
                }[metric]
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
        symbol=s.symbol,
        timeframe=timeframe_label(s.seconds),
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
    return dict(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        summary=summary,
        trades=trades,
        equity=curve,
        events=events,
        diagnostics=warnings,
    )
