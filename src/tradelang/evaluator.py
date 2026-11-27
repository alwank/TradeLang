"""Causal numeric series. NaN is internal unavailable, including Boolean predicates."""

import numpy as np

from .compiler import BINARY, COMPARE
from .functions.contracts import KernelContext
from .functions.kernels import lag
from .functions.profile import profile_key
from .functions.registry import FUNCTIONS


class Evaluator:
    def __init__(
        self,
        strategy,
        dataset,
        end,
        *,
        profiles=None,
        feeds=None,
        active_clock=None,
        invalid=None,
    ):
        self.columns = {
            k: dataset.column(k)[: end + 1]
            for k in ("open", "high", "low", "close", "volume")
        }
        self.n = end + 1
        self.times = dataset.times[: self.n]
        self.session_rows = (
            dataset.session_rows if strategy.config.calendar == "session" else None
        )
        self.times.flags.writeable = False
        self.timeframe_seconds = (
            dataset.timeframe_seconds
            if active_clock is not None or strategy.seconds is None
            else strategy.seconds
        )
        self.profiles = {} if profiles is None else profiles
        for column in self.columns.values():
            column.flags.writeable = False
        self.names = {n: e for n, e, _ in strategy.bindings}
        self.parameters = {
            parameter.name: parameter.value for parameter in strategy.parameters
        }
        self.cache = {}
        self.invalid = {} if invalid is None else invalid
        self.call_cache = {}
        self.active_clock = active_clock
        self.feeds = feeds or {}
        self.secondary = {
            name: Evaluator(
                strategy,
                item.dataset,
                item.rows - 1,
                active_clock=name,
                invalid=self.invalid,
            )
            for name, item in self.feeds.items()
        }

    def domain(self, expression):
        if expression.type.clock == self.active_clock or expression.type.clock is None:
            return self
        return self.secondary[expression.type.clock]

    def aligned_row(self, feed, primary_row):
        return int(self.feeds[feed].indices[primary_row]) if primary_row >= 0 else -1

    def close_at(self, row):
        if self.session_rows is not None:
            return self.session_rows.close[row]
        return self.times[row] + self.timeframe_seconds * 1_000_000

    def array(self, x):
        return np.broadcast_to(x, (self.n,))

    def value(self, e, i, equity=None):
        if i < 0:
            return None
        if e.account:
            if e.op == "account":
                return equity
            if equity is None:
                return None
            vals = [self.value(c, i, equity) for c in e.args]
            if any(x is None for x in vals) and e.op != "choice":
                return None
            try:
                with np.errstate(all="ignore"):
                    v = self.operation(
                        e, [np.nan if value is None else value for value in vals]
                    )
            except ArithmeticError:
                return None
            return float(v) if np.isfinite(v) else None
        x = self.evaluate(e)
        v = x[i] if np.ndim(x) else x
        return float(v) if np.isfinite(v) else None

    def evaluate(self, e):
        domain = self.domain(e)
        if domain is not self:
            return domain.evaluate(e)
        if e in self.cache:
            return self.cache[e]
        args = (
            []
            if e.op == "align" and not self.secondary[e.value].n
            else [self.evaluate(c) for c in e.args]
        )
        with np.errstate(all="ignore"):
            out = self.operation(e, args)
        if isinstance(out, np.ndarray) and out.ndim and e.op not in ("builtin", "let"):
            self.invalid["warmup"] = self.invalid.get("warmup", 0) + min(
                e.ready, self.n
            )
            overflow = int(np.isinf(out).sum())
            if e.op == "binary" and e.value == "/":
                overflow = int(
                    np.count_nonzero(np.isinf(out) & (np.asarray(args[1]) != 0))
                )
            if overflow:
                self.invalid["overflow"] = self.invalid.get("overflow", 0) + overflow
            if e.op == "binary" and e.value == "**":
                bad = np.isnan(out) & np.isfinite(args[0]) & np.isfinite(args[1])
                self.invalid["domain"] = self.invalid.get("domain", 0) + int(bad.sum())
        if isinstance(out, dict):
            out = {k: np.where(np.isfinite(v), v, np.nan) for k, v in out.items()}
        elif isinstance(out, np.ndarray):
            if np.isinf(out).any():
                out = np.where(np.isfinite(out), out, np.nan)
        self.cache[e] = out
        return out

    def operation(self, e, args):
        match e.op:
            case "literal":
                return e.value
            case "parameter":
                return self.parameters[e.value]
            case "builtin":
                return self.columns[e.value]
            case "let":
                return self.evaluate(self.names[e.value])
            case "on_feed":
                return args[0]
            case "align":
                alignment = self.feeds[e.value]
                output = np.full(self.n, np.nan)
                valid = alignment.status[: self.n] == 0
                if args:
                    output[valid] = args[0][alignment.indices[: self.n][valid]]
                return output
            case "field":
                return args[0][e.value]
            case "offset":
                return lag(args[0], e.value)
            case "call":
                key = (
                    e.value,
                    tuple(id(x) if isinstance(x, np.ndarray) else x for x in args),
                )
                if key not in self.call_cache:
                    function = FUNCTIONS[e.value]
                    context = KernelContext(
                        {
                            name: self.columns[name]
                            for name in function.required_columns
                        },
                        self.invalid,
                        self.times if function.requires_clock else None,
                        self.timeframe_seconds if function.requires_clock else None,
                        self.profiles[profile_key(args)]
                        if function.requires_profile
                        else None,
                        session_ids=self.session_rows.session_index[: self.n]
                        if self.session_rows is not None and function.requires_clock
                        else None,
                    )
                    self.call_cache[key] = function.kernel(args, context)
                return self.call_cache[key]
            case "unary":
                return args[0] if e.value == "+" else -args[0]
            case "binary":
                a, b = args
                if e.value == "/":
                    zeros = int(np.count_nonzero(np.asarray(b) == 0))
                    if zeros:
                        self.invalid["zero_denominator"] = (
                            self.invalid.get("zero_denominator", 0) + zeros
                        )
                    return np.divide(a, b)
                if e.value == "**":
                    return np.where(
                        ~np.isfinite(a)
                        | ~np.isfinite(b)
                        | ((np.asarray(a) == 0) & (np.asarray(b) == 0)),
                        np.nan,
                        np.float_power(a, b),
                    )
                return BINARY[e.value](a, b)
            case "compare":
                a, b = args
                return np.where(
                    np.isfinite(a) & np.isfinite(b), COMPARE[e.value](a, b), np.nan
                )
            case "cross":
                a, b = map(self.array, args)
                ap, bp = lag(a, 1), lag(b, 1)
                result = (
                    (ap <= bp) & (a > b) if e.value == "above" else (ap >= bp) & (a < b)
                )
                return np.where(
                    np.isfinite(a) & np.isfinite(b) & np.isfinite(ap) & np.isfinite(bp),
                    result,
                    np.nan,
                )
            case "bool":
                a = args[0]
                b = args[-1]
                result = (
                    np.logical_not(a)
                    if e.value == "not"
                    else (np.logical_and if e.value == "and" else np.logical_or)(a, b)
                )
                return np.where(np.isfinite(a) & np.isfinite(b), result, np.nan)
            case "choice":
                first = args[0]
                if e.value == "available":
                    return np.where(np.isfinite(first), 1.0, 0.0)
                if e.value == "coalesce":
                    return np.where(np.isfinite(first), first, args[1])
                return np.where(
                    np.isfinite(first), np.where(first == 1, args[1], args[2]), np.nan
                )
            case _:
                raise AssertionError(e.op)
