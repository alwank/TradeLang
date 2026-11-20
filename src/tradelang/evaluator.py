"""Causal numeric series. NaN is internal unavailable, including Boolean predicates."""

import numpy as np

from .compiler import BINARY, COMPARE
from .functions.contracts import KernelContext
from .functions.kernels import lag
from .functions.registry import FUNCTIONS


class Evaluator:
    def __init__(self, strategy, dataset, end):
        self.columns = {
            k: dataset.column(k)[: end + 1]
            for k in ("open", "high", "low", "close", "volume")
        }
        self.n = end + 1
        self.names = {n: e for n, e, _ in strategy.bindings}
        self.cache = {}
        self.invalid = {}
        self.call_cache = {}

    def array(self, x):
        return np.broadcast_to(x, (self.n,))

    def value(self, e, i, equity=None):
        if e.account:
            if e.op == "account":
                return equity
            if equity is None:
                return None
            vals = [self.value(c, i, equity) for c in e.args]
            if any(x is None for x in vals):
                return None
            try:
                with np.errstate(all="ignore"):
                    v = self.operation(e, vals)
            except ArithmeticError:
                return None
            return float(v) if np.isfinite(v) else None
        x = self.evaluate(e)
        v = x[i] if np.ndim(x) else x
        return float(v) if np.isfinite(v) else None

    def evaluate(self, e):
        if e in self.cache:
            return self.cache[e]
        args = [self.evaluate(c) for c in e.args]
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
            case "builtin":
                return self.columns[e.value]
            case "let":
                return self.evaluate(self.names[e.value])
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
                        {name: self.columns[name] for name in function.required_columns},
                        self.invalid,
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
            case _:
                raise AssertionError(e.op)
