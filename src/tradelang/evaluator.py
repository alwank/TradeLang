"""Causal numeric series. NaN is internal unavailable, including Boolean predicates."""

import numpy as np

from .compiler import BINARY, COMPARE
from .functions.contracts import KernelContext
from .functions.registry import FUNCTIONS


def lag(a, n):
    if n == 0:
        return a
    out = np.full(len(a), np.nan)
    if n < len(a):
        out[n:] = a[:-n]
    return out


def rolling(x, n, fn):
    out = np.full(len(x), np.nan)
    if n <= len(x):
        windows = np.lib.stride_tricks.sliding_window_view(x, n)
        # Bound work buffers for two-pass standard deviation.
        step = max(1, 1000000 // n)
        for i in range(0, len(windows), step):
            block = windows[i : i + step]
            if fn in (np.mean, np.std):
                # accumulate follows the time axis in order for each reference window.
                mean = np.add.accumulate(block, axis=1)[:, -1] / n
                result = (
                    mean
                    if fn is np.mean
                    else np.sqrt(
                        np.add.accumulate((block - mean[:, None]) ** 2, axis=1)[:, -1]
                        / n
                    )
                )
            else:
                result = fn(block, axis=1)
            out[n - 1 + i : n - 1 + i + len(block)] = result
    return out


def smooth(x, n, wilder=False):
    out = np.full(len(x), np.nan)
    seen = 0
    total = 0.0
    prev = 0.0
    alpha = 2 / (n + 1)
    for i, v in enumerate(x):
        if not np.isfinite(v):
            seen = 0
            total = 0.0
            continue
        if seen < n:
            total += v
            seen += 1
            if seen < n:
                continue
            prev = total / n
        elif wilder:
            prev = (prev * (n - 1) + v) / n
        else:
            prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def indicator(name, args, columns, invalid_counts):
    if name == "ATR":
        h, low, c = (columns[k] for k in ("high", "low", "close"))
        tr = h - low
        tr[1:] = np.maximum(
            tr[1:], np.maximum(abs(h[1:] - c[:-1]), abs(low[1:] - c[:-1]))
        )
        return smooth(tr, int(args[0]), True)
    x = args[0]
    n = int(args[1])
    if name == "EMA":
        return smooth(x, n)
    if name == "RSI":
        delta = x - lag(x, 1)
        g = smooth(np.maximum(0, delta), n, True)
        loss = smooth(np.maximum(0, -delta), n, True)
        return np.where(
            loss == 0, np.where(g == 0, 50.0, 100.0), 100 - 100 / (1 + g / loss)
        )
    if name == "MACD":
        line = smooth(x, n) - smooth(x, int(args[2]))
        signal = smooth(line, int(args[3]))
        return dict(line=line, signal=signal, histogram=line - signal)
    if name == "ROC":
        prior = lag(x, n)
        missing = np.cumsum(~np.isfinite(x))
        invalid = missing - np.pad(missing, (n + 1, 0))[: len(x)]
        complete = (np.arange(len(x)) >= n) & (invalid == 0)
        zeros = complete & (prior == 0)
        usable = complete & ~zeros
        values = np.divide(x, prior, out=np.full(len(x), np.nan), where=usable) - 1
        overflow = usable & ~np.isfinite(values)
        for reason, mask in (("zero_denominator", zeros), ("overflow", overflow)):
            count = int(np.count_nonzero(mask))
            if count:
                invalid_counts[reason] = invalid_counts.get(reason, 0) + count
        values[overflow] = np.nan
        return values
    if name == "BBANDS":
        mid = rolling(x, n, np.mean)
        width = rolling(x, n, np.std) * args[2]
        return dict(middle=mid, upper=mid + width, lower=mid - width)
    return rolling(
        x,
        n,
        {"SMA": np.mean, "STDDEV": np.std, "HIGHEST": np.max, "LOWEST": np.min}[name],
    )


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
                    if e.value in {"SMA", "STDDEV", "HIGHEST", "LOWEST", "BBANDS"}:
                        function = FUNCTIONS[e.value]
                        context = KernelContext(
                            {name: self.columns[name] for name in function.required_columns},
                            self.invalid,
                        )
                        self.call_cache[key] = function.kernel(args, context)
                    else:
                        self.call_cache[key] = indicator(
                            e.value, args, self.columns, self.invalid
                        )
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
