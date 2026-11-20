"""Compile TradeLang source into an immutable, dimension-checked expression graph."""

from __future__ import annotations

import difflib
import json
import math
import operator
import re
from datetime import date
from functools import cache
from importlib.resources import files

from lark import Lark, UnexpectedInput

from .functions.contracts import Argument, InvalidCall
from .functions.registry import FUNCTIONS
from .model import (
    COUNT,
    MONEY,
    PRICE,
    RATIO,
    UNITS,
    VOLUME,
    Config,
    Expr,
    Problem,
    Span,
    Strategy,
    Type,
)

GRAMMAR = files("tradelang").joinpath("grammar-v1.lark").read_text()
OPS = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
    "exponent": "**",
    "positive": "+",
    "negative": "-",
    "greater": ">",
    "less": "<",
    "equal": "==",
    "not_equal": "!=",
    "greater_equal": ">=",
    "less_equal": "<=",
}
BINARY = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "**": operator.pow,
}
COMPARE = {
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
}
PRICES = {"open", "high", "low", "close"}
RESERVED = set(re.findall(r"_K_([A-Z]+)\.2:", GRAMMAR.lower(), re.IGNORECASE)) | PRICES
RESERVED.update(
    [
        "equity",
        "volume",
        "money",
        "count",
        "price",
    ]
)
RESERVED.update(field.name for function in FUNCTIONS.values() for field in function.fields)


@cache
def parser():
    return Lark(GRAMMAR, parser="lalr", lexer="contextual", propagate_positions=True)


def seconds(raw):
    return int(raw[:-1]) * {"m": 60, "h": 3600, "d": 86400}[raw[-1]]


class Compiler:
    def __init__(self, source):
        self.raw = source
        if len(source) > 65536:
            raise Problem("E207_LIMIT", "Strategy exceeds 64 KiB")
        self.text = source.decode("utf-8-sig")
        self.bytes = [len(source) - len(self.text.encode())]
        for char in self.text:
            self.bytes.append(self.bytes[-1] + len(char.encode()))
        self.names = {}
        self.declared = set()
        self.used = set()
        self.calls = set()
        self.nodes = 0
        self.warnings = []

    def span(self, t):
        m = t.meta
        return Span(
            start_line=m.line,
            start_column=m.column,
            end_line=m.end_line,
            end_column=m.end_column,
            start_byte=self.bytes[m.start_pos],
            end_byte=self.bytes[m.end_pos],
        )

    def fail(self, t, code, message, suggestion=None):
        raise Problem(code, message, self.span(t), suggestion)

    def expr(self, t, account=False, depth=0):
        self.nodes += 1
        if depth > 64 or self.nodes > 2048:
            self.fail(t, "E207_LIMIT", "Expression depth or node limit exceeded")
        op = str(t.data)
        c = t.children

        def sub(tree):
            return self.expr(tree, account, depth + 1)

        def build(tag, val, args, typ, ready=None, constant=None):
            warm = max((a.ready for a in args), default=0) if ready is None else ready
            if warm > 100000:
                self.fail(t, "E207_LIMIT", "History exceeds 100000 bars")
            return Expr(
                tag,
                val,
                tuple(args),
                typ,
                warm,
                self.span(t),
                constant,
                tag == "account" or any(a.account for a in args),
            )

        if op == "grouped":
            return sub(c[0])
        if op in {"true", "false", "number", "percent", "typed_number"}:
            boolean = op in {"true", "false"}
            value: float | bool = (
                (op == "true")
                if boolean
                else float(c[0]) / (100 if op == "percent" else 1)
            )
            if not math.isfinite(value):
                self.fail(t, "E206_CONSTANT_INVALID", "Nonfinite literal")
            unit = UNITS[str(c[1])] if op == "typed_number" else RATIO
            return build(
                "literal",
                value,
                [],
                Type("boolean" if boolean else "numeric", False, unit),
                constant=value,
            )
        if op == "reference":
            name = str(c[0])
            if name in PRICES | {"volume"}:
                return build(
                    "builtin",
                    name,
                    [],
                    Type("numeric", True, VOLUME if name == "volume" else PRICE),
                )
            if name == "equity" and account:
                return build("account", name, [], Type(unit=MONEY))
            if name not in self.names:
                if name in self.declared:
                    self.fail(
                        t,
                        "E104_FORWARD_REFERENCE",
                        f"Binding {name} must be declared earlier",
                    )
                choices = difflib.get_close_matches(
                    name, list(self.names) + sorted(PRICES | {"volume"}), n=1
                )
                self.fail(
                    t,
                    "E102_UNKNOWN_NAME",
                    f"Unknown or unavailable name {name}",
                    choices[0] if choices else None,
                )
            e = self.names[name]
            self.used.add(name)
            return build("let", name, [], e.type, e.ready, e.constant)
        if op == "postfix":
            self.nodes += len(c) - 1
            if depth + len(c) > 64 or self.nodes > 2048:
                self.fail(t, "E207_LIMIT", "Postfix chain exceeds expression limits")
            e = sub(c[0])
            for suffix in c[1:]:
                if suffix.data == "field":
                    field = str(suffix.children[0])
                    if field not in e.type.fields:
                        self.fail(
                            suffix,
                            "E204_SELECTOR",
                            f"Unknown field {field} for this expression",
                        )
                    ready = FUNCTIONS[e.value].field_ready(field, e.args)
                    e = build(
                        "field", field, [e], Type("numeric", True, e.type.unit), ready
                    )
                else:
                    if len(str(suffix.children[0])) > 6:
                        self.fail(suffix, "E205_OFFSET", "Maximum offset is 100000")
                    bars = int(suffix.children[0])
                    if (
                        not e.type.series
                        or e.type.kind != "numeric"
                        or e.account
                        or bars > 100000
                    ):
                        self.fail(
                            suffix,
                            "E205_OFFSET",
                            "Offset requires numeric market series and 0..100000 bars",
                        )
                    e = build("offset", bars, [e], e.type, e.ready + bars)
            return e
        if op == "function":
            return self.call(t, sub, build)
        args = [sub(x) for x in (c[::2] if op == "compare" else c)]
        a = args[0]
        b = args[-1]
        series = any(x.type.series for x in args)
        if op.startswith("bool_"):
            if any(x.type.kind != "boolean" for x in args):
                self.fail(t, "E203_TYPE", "Boolean operands required")
            return build("bool", op[5:], args, Type("boolean", series))
        if any(x.type.kind != "numeric" for x in args):
            self.fail(t, "E203_TYPE", "Numeric operands required")
        if op == "compare" or op.startswith("crosses_"):
            if a.type.unit != b.type.unit and not any(
                x.op == "literal" and x.value == 0 and x.type.unit == RATIO
                for x in args
            ):
                self.fail(
                    t,
                    "E201_UNIT",
                    "Compare compatible units; use an explicit numeric unit",
                )
            if any(
                x.op == "call" and FUNCTIONS[x.value].scale == "points" for x in args
            ) and any(
                x.data == "percent" for x in (c[0], c[-1])
            ):
                w = Problem(
                    "W_RSI_SCALE",
                    "RSI uses a 0 to 100 scale. A percentage threshold is a fraction.",
                    self.span(t),
                ).diagnostic
                self.warnings.append({**w, "severity": "warning"})
            cross = op != "compare"
            return build(
                "cross" if cross else "compare",
                op[8:] if cross else OPS[str(c[1].data)],
                args,
                Type("boolean", series or cross),
                max(x.ready for x in args) + int(cross),
            )
        symbol = OPS[op]
        unit = a.type.unit
        other = b.type.unit
        if len(args) == 1:
            val = a.constant
            return build(
                "unary",
                symbol,
                args,
                a.type,
                constant=(-val if symbol == "-" else val) if val is not None else None,
            )
        if symbol in "+-" and unit != other:
            self.fail(
                t,
                "E201_UNIT",
                "Addition and subtraction require equal units",
                "For a relative price move use close * (1 + 2%)",
            )
        if symbol in "*/":
            if COUNT in (unit, other):
                if unit == other and symbol == "/":
                    unit = RATIO
                elif other == RATIO or (unit == RATIO and symbol == "*"):
                    unit = COUNT
                else:
                    self.fail(t, "E201_UNIT", "Unsupported count arithmetic")
            else:
                unit = tuple(
                    i + j if symbol == "*" else i - j for i, j in zip(unit, other)
                )
        if symbol == "**":
            power = b.constant
            if (
                power is None
                or other != RATIO
                or unit == COUNT
                or abs(power) > (16 if unit == RATIO else 8)
                or (unit != RATIO and not float(power).is_integer())
            ):
                self.fail(t, "E203_TYPE", "Invalid exponent or exponent dimension")
            if unit != RATIO:
                unit = tuple(int(i * power) for i in unit)
        if unit != COUNT and max(map(abs, unit)) > 8:
            self.fail(t, "E201_UNIT", "Dimension exponent exceeds 8")
        if symbol == "/" and b.constant == 0:
            self.fail(t, "E206_CONSTANT_INVALID", "Division by constant zero")
        folded = None
        if a.constant is not None and b.constant is not None:
            try:
                folded = BINARY[symbol](a.constant, b.constant)
                if not math.isfinite(folded) or (
                    symbol == "**" and a.constant == b.constant == 0
                ):
                    raise ValueError()
            except (ArithmeticError, TypeError, ValueError):
                self.fail(t, "E206_CONSTANT_INVALID", "Invalid constant arithmetic")
        return build(
            "binary", symbol, args, Type("numeric", series, unit), constant=folded
        )

    def call(self, t, sub, build):
        function = FUNCTIONS[str(t.children[0])]
        trees = t.children[1].children if len(t.children) > 1 else ()
        arguments = [
            Argument(sub(tree), str(tree.children[0]) if tree.data == "number" else None)
            for tree in trees
        ]

        def default_close():
            return build("builtin", "close", [], Type("numeric", True, PRICE))

        try:
            args = function.bind(arguments, default_close)
        except InvalidCall as error:
            origin = t if error.argument is None else trees[error.argument]
            self.fail(origin, error.code, str(error))
        self.calls.add(t)
        if len(self.calls) > 128:
            self.fail(t, "E207_LIMIT", "More than 128 unique indicator calls")
        return build(
            "call", function.name, args, function.output_type(args), function.readiness(args)
        )

    def compile(self):
        try:
            tree = parser().parse(self.text)
        except UnexpectedInput as exc:
            i = max(0, exc.pos_in_stream or 0)
            span = Span(
                start_line=max(1, exc.line),
                start_column=max(1, exc.column),
                end_line=max(1, exc.line),
                end_column=max(1, exc.column) + 1,
                start_byte=self.bytes[i],
                end_byte=self.bytes[min(i + 1, len(self.text))],
            )
            raise Problem(
                "E101_SYNTAX",
                "Unexpected syntax near " + repr(self.text[i : i + 20]),
                span,
                "Expected "
                + ", ".join(
                    sorted(
                        getattr(exc, "expected", [])
                        or getattr(exc, "allowed", [])
                        or []
                    )[:5]
                ),
            ) from exc
        self.declared = {
            str(t.children[0]) for t in tree.children if t.data == "let_decl"
        }
        blocks = {str(t.data): t for t in tree.children}

        def children(name):
            return blocks[name].children

        spans = {k: self.span(v).model_dump() for k, v in blocks.items()}
        spans["start"] = Span(
            start_line=1,
            start_column=1,
            start_byte=self.bytes[0],
            end_byte=len(self.raw),
            end_line=self.text.count("\n") + 1,
            end_column=len(self.text.rsplit("\n", 1)[-1]) + 1,
        ).model_dump()
        bindings: list[tuple[str, Expr, Span]] = []
        for t in tree.children:
            if t.data != "let_decl":
                continue
            name = str(t.children[0])
            if name in RESERVED or name in self.names:
                self.fail(
                    t, "E103_DUPLICATE_BINDING", f"Reserved or duplicate name {name}"
                )
            if len(bindings) >= 128:
                self.fail(t, "E207_LIMIT", "More than 128 lets")
            e = self.expr(t.children[1])
            if e.type.kind not in {"numeric", "boolean"}:
                self.fail(
                    t, "E203_TYPE", "let requires a numeric or Boolean expression"
                )
            bindings.append((name, e, self.span(t)))
            self.names[name] = e
        entry = self.expr(children("entry")[0])
        exit_expr = self.expr(children("exit")[0])
        for e in (entry, exit_expr):
            if e.type.kind != "boolean":
                raise Problem("E203_TYPE", "when requires a Boolean condition", e.span)
        sizing_tree = children("entry")[1]
        spans["sizing"] = self.span(sizing_tree).model_dump()
        sizing = self.expr(sizing_tree.children[0], True)
        fixed = sizing_tree.data == "fixed_money"
        if sizing.type.kind != "numeric" or sizing.type.unit not in (
            (RATIO, MONEY) if fixed else (RATIO,)
        ):
            self.fail(sizing_tree, "E302_SIZING", "Invalid sizing dimension")
        if sizing.constant is not None and (
            sizing.constant <= 0 or (not fixed and sizing.constant > 1)
        ):
            self.fail(sizing_tree, "E302_SIZING", "Invalid sizing amount")
        rules = {}
        if "risk" in blocks and not children("risk"):
            self.fail(blocks["risk"], "E303_RISK", "Empty risk section")
        for t in children("risk") if "risk" in blocks else []:
            if t.data == "max_positions":
                continue
            e = self.expr(t.children[0])
            if (
                e.type.kind != "numeric"
                or e.type.unit not in (RATIO, PRICE)
                or (
                    e.constant is not None
                    and (
                        e.constant <= 0
                        or (
                            t.data == "stop"
                            and e.type.unit == RATIO
                            and e.constant >= 1
                        )
                    )
                )
            ):
                self.fail(t, "E303_RISK", "Invalid risk distance")
            spans[str(t.data)] = self.span(t).model_dump()
            rules[str(t.data)] = e
        w, capital, fee, slip, *_ = children("backtest")
        a, b = map(str, w.children)
        try:
            if (
                date.fromisoformat(a) > date.fromisoformat(b)
                or date.fromisoformat(b) == date.max
            ):
                raise ValueError()
        except ValueError:
            self.fail(w, "E402_WINDOW", "Invalid inclusive date window")
        cfg = Config(
            a,
            b,
            float(capital.children[0]),
            str(capital.children[1]),
            float(fee.children[0]) / 10000,
            float(slip.children[0]) / 10000,
        )
        if (
            not math.isfinite(cfg.capital)
            or cfg.capital <= 0
            or max(cfg.fee_rate, cfg.slippage_rate) >= 1
        ):
            self.fail(blocks["backtest"], "E302_SIZING", "Invalid capital or cost rate")
        if fixed and sizing_tree.children[1] != cfg.currency:
            self.fail(
                sizing_tree, "E302_SIZING", "Sizing currency differs from capital"
            )
        if len(str(children("timeframe")[0])) > 7:
            self.fail(
                blocks["timeframe"], "E207_LIMIT", "Maximum timeframe is seven days"
            )
        duration = seconds(str(children("timeframe")[0]))
        if duration > 604800:
            self.fail(
                blocks["timeframe"], "E207_LIMIT", "Maximum timeframe is seven days"
            )
        try:
            name = json.loads(children("header")[0])
        except ValueError:
            self.fail(blocks["header"], "E101_SYNTAX", "Invalid JSON string")
        if not 1 <= len(name) <= 120 or not name.isprintable():
            self.fail(blocks["header"], "E101_SYNTAX", "Invalid strategy name")
        for label, _, span in bindings:
            if label not in self.used:
                d = Problem(
                    "W_UNUSED_LET", f"Unused let {label} counts toward warmup", span
                ).diagnostic
                self.warnings.append({**d, "severity": "warning"})
        return Strategy(
            self.raw,
            name,
            str(children("market")[0]),
            duration,
            tuple(bindings),
            entry,
            exit_expr,
            sizing,
            fixed,
            rules.get("stop"),
            rules.get("target"),
            cfg,
            spans,
            tuple(self.warnings),
        )


def compile_source(source: bytes | str) -> Strategy:
    try:
        return Compiler(
            source.encode() if isinstance(source, str) else source
        ).compile()
    except UnicodeError as exc:
        raise Problem("E101_SYNTAX", "Expected UTF-8 source") from exc
    except (RecursionError, OverflowError) as exc:
        raise Problem("E207_LIMIT", "Expression exceeds compiler limits") from exc
