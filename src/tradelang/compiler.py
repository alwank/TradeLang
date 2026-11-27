"""Compile TradeLang source into an immutable, dimension-checked expression graph."""

from __future__ import annotations

import difflib
import json
import math
import operator
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Literal, cast

from lark import Lark, UnexpectedInput
from lark.utils import TextSlice

from .functions.contracts import Argument, InvalidCall
from .functions.profile import MAX_PROFILE_CALLS, ProfileKey, profile_key
from .functions.registry import FUNCTIONS
from .model import (
    COUNT,
    MONEY,
    PARAMETER_KINDS,
    PRICE,
    RATIO,
    UNITS,
    VOLUME,
    Config,
    ExitRule,
    Expr,
    Feed,
    Parameter,
    ParameterKind,
    ParameterValue,
    Problem,
    Scale,
    ScaleRule,
    SellSize,
    ShortMargin,
    Span,
    Strategy,
    Type,
)

if TYPE_CHECKING:
    from .portfolio import PortfolioSpec

GRAMMAR = files("tradelang").joinpath("grammar-v1.lark").read_text()
GRAMMAR_V2 = files("tradelang").joinpath("grammar-v2.lark").read_text()
GRAMMAR_V3 = files("tradelang").joinpath("grammar-v3.lark").read_text()
GRAMMAR_V4 = files("tradelang").joinpath("grammar-v4.lark").read_text()
GRAMMAR_V5 = files("tradelang").joinpath("grammar-v5.lark").read_text()
GRAMMAR_V6 = files("tradelang").joinpath("grammar-v6.lark").read_text()
GRAMMAR_V7 = files("tradelang").joinpath("grammar-v7.lark").read_text()
GRAMMAR_V8 = files("tradelang").joinpath("grammar-v8.lark").read_text()
IGNORED_PREFIX = re.compile(r"(?:[ \t\r\n\f]|#[^\r\n]*(?=[\r\n]|\Z))*")
VERSION_PREFIX = re.compile(r"tradelang\b")
MODERN_VERSION = re.compile(r"[2345678](?![A-Za-z0-9_.])")
PORTFOLIO_DIRECTIVE = re.compile(r"9(?![A-Za-z0-9_.])")
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
TOKEN_LABELS = {
    "$END": "the end of the strategy",
    "CURRENCY": "a quote currency such as USDT",
    "DATE": "a date in YYYY-MM-DD form",
    "FUNCTION": "an uppercase indicator name",
    "NAME": "a lowercase name",
    "NUMBER": "a numeric literal",
    "STRING": "a double-quoted strategy name",
    "SYMBOL": "an uppercase market symbol",
    "TIMEFRAME": "a timeframe such as 1h",
    "UINT": "a nonnegative integer",
    "UNIT": "a unit such as price",
    "PARAM_TYPE": "count, ratio, price, or bool",
}
CALL_START = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CALL_NAME_BEFORE_PAREN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\Z")
EDITOR_SECTIONS = re.compile(
    r"^[ \t]*(?:(let|param|feed)[ \t]+([a-z_][a-z0-9_]*)\b"
    r"|(entry|exit|scale|risk|backtest)[ \t]*:)",
    re.M,
)
MAX_EDITOR_ERRORS = 8
MAX_EDITOR_SECTIONS = 32
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
# v1 reserved these selectors before the catalog expanded. New selectors
# are contextual after a dot, so adding them preserves existing let names.
RESERVED.update(("line", "signal", "histogram", "upper", "middle", "lower"))
RESERVED_V2 = RESERVED | set(
    re.findall(r"_K_([A-Z]+)\.2:", GRAMMAR_V2.lower(), re.IGNORECASE)
)
RESERVED_V3 = RESERVED_V2 | {"feed", "max_age", "on", "align", "primary"}
RESERVED_V4 = RESERVED_V3 | {"risking", "allocation"}
RESERVED_V5 = RESERVED_V4 | {"rule", "after", "bars", "trailing", "expire"}
RESERVED_V6 = RESERVED_V5 | {
    "position",
    "units",
    "scale",
    "add",
    "cash",
    "quantity",
    "step",
}
RESERVED_V7 = RESERVED_V6 | {"session"}
RESERVED_V8 = RESERVED_V7 | {
    "short",
    "cover",
    "initial",
    "margin",
    "maintenance",
    "borrow",
    "day",
}


def grammar_for(version):
    return "\n".join(
        (
            GRAMMAR,
            GRAMMAR_V2,
            GRAMMAR_V3,
            GRAMMAR_V4,
            GRAMMAR_V5,
            GRAMMAR_V6,
            GRAMMAR_V7,
            GRAMMAR_V8,
        )[:version]
    )


@cache
def parser(version=1):
    return Lark(
        grammar_for(version),
        parser="lalr",
        lexer="contextual",
        propagate_positions=True,
    )


@cache
def editor_parser(version):
    starts = ["let_decl", "entry", "exit", "risk", "backtest"]
    if version >= 2:
        starts.append("param_decl")
    if version >= 3:
        starts.append("feed_decl")
    if version >= 6:
        starts.append("scale")
    return Lark(
        grammar_for(version),
        parser="lalr",
        lexer="contextual",
        propagate_positions=True,
        start=starts,
    )


def source_version(text: str) -> Literal[1, 2, 3, 4, 5, 6, 7, 8]:
    prefix = VERSION_PREFIX.match(text, ignored_end(text, 0))
    if prefix is not None and (
        match := MODERN_VERSION.match(text, ignored_end(text, prefix.end()))
    ):
        return cast(Literal[2, 3, 4, 5, 6, 7, 8], int(match[0]))
    return 1


def ignored_end(text, start):
    match = IGNORED_PREFIX.match(text, start)
    return match.end() if match else start


def is_portfolio_source(source: bytes) -> bool:
    text = source.decode("utf-8-sig", errors="replace")
    prefix = VERSION_PREFIX.match(text, ignored_end(text, 0))
    return (
        prefix is not None
        and PORTFOLIO_DIRECTIVE.match(text, ignored_end(text, prefix.end())) is not None
    )


def seconds(raw):
    return int(raw[:-1]) * {"m": 60, "h": 3600, "d": 86400}[raw[-1]]


def syntax_expectation(expected, version):
    labels = []
    patterns = {
        terminal.name: terminal.pattern for terminal in parser(version).terminals
    }
    for name in sorted(expected):
        if name in TOKEN_LABELS:
            labels.append(TOKEN_LABELS[name])
            continue
        pattern = patterns.get(name)
        if pattern is None:
            continue
        if pattern.type == "str":
            labels.append(repr(pattern.value))
        elif name.startswith("_K_") or name == "_TRADELANG_VERSION_PREFIX":
            labels.append(repr(pattern.value.removeprefix(r"\b").removesuffix(r"\b")))
    return "Expected " + ", ".join(labels[:5]) if labels else None


class UnavailableBinding(Exception):
    """A failed earlier declaration blocks independent validation of an expression."""


class Compiler:
    def __init__(self, source, parameters=None):
        self.raw = source
        if len(source) > 65536:
            raise Problem("E207_LIMIT", "Strategy exceeds 64 KiB")
        self.text = source.decode("utf-8-sig")
        self.version = source_version(self.text)
        self.overrides = {} if parameters is None else dict(parameters)
        self.parameters: dict[str, Parameter] = {}
        self.feed: Feed | None = None
        self.clock: str | None = None
        self.reserved = (
            RESERVED,
            RESERVED_V2,
            RESERVED_V3,
            RESERVED_V4,
            RESERVED_V5,
            RESERVED_V6,
            RESERVED_V7,
            RESERVED_V8,
        )[self.version - 1]
        self.bytes = [len(source) - len(self.text.encode())]
        for char in self.text:
            self.bytes.append(self.bytes[-1] + len(char.encode()))
        self.names = {}
        self.declared = set()
        self.unavailable_bindings: set[str] = set()
        self.used = set()
        self.calls = set()
        self.profile_calls: set[ProfileKey] = set()
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

    def syntax_problem(self, error, *, end_of_section=None):
        expected = (
            getattr(error, "expected", None) or getattr(error, "allowed", None) or ()
        )
        eof = getattr(getattr(error, "token", None), "type", None) == "$END"
        start = (
            (len(self.text) if end_of_section is None else end_of_section)
            if eof
            else max(0, error.pos_in_stream or 0)
        )
        end = start if eof else min(start + 1, len(self.text))
        suggestion = syntax_expectation(expected, self.version)
        message = (
            (
                "Unexpected syntax at the end of the strategy"
                if end_of_section is None
                else "Unexpected syntax at the end of this section"
            )
            if eof
            else "Unexpected syntax near " + repr(self.text[start : start + 20])
        )
        call = None
        if self.text[start : start + 1] == "(":
            call = CALL_NAME_BEFORE_PAREN.search(self.text, 0, start)
        elif "FUNCTION" in expected:
            call = CALL_START.match(self.text, start)
        if call is not None and call[1] not in FUNCTIONS:
            name = call[1]
            start, end = call.span(1)
            if name.upper() in FUNCTIONS:
                message = f"Indicator names are uppercase. Found {name!r}."
                suggestion = f"Use {name.upper()}(...)"
            else:
                message = f"Unknown indicator {name!r}"
                matches = difflib.get_close_matches(name.upper(), FUNCTIONS, n=2)
                suggestion = (
                    "Check the spelling. Did you mean "
                    + " or ".join(f"{match}(...)" for match in matches)
                    + "?"
                    if matches
                    else "Use an indicator from the TradeLang indicator reference"
                )
        return Problem(
            "E101_SYNTAX",
            message,
            Span(
                start_line=self.text.count("\n", 0, start) + 1,
                start_column=start - self.text.rfind("\n", 0, start),
                end_line=self.text.count("\n", 0, end) + 1,
                end_column=end - self.text.rfind("\n", 0, end),
                start_byte=self.bytes[start],
                end_byte=self.bytes[end],
            ),
            suggestion,
        )

    def expr(self, t, account=False, depth=0):
        self.nodes += 1
        if depth > 64 or self.nodes > 2048:
            self.fail(t, "E207_LIMIT", "Expression depth or node limit exceeded")
        op = str(t.data)
        c = t.children

        def sub(tree):
            return self.expr(tree, account, depth + 1)

        def build(tag, val, args, typ, ready=None, constant=None):
            if typ.series and tag != "align":
                clocks = {arg.type.clock for arg in args if arg.type.series}
                if len(clocks) > 1:
                    self.fail(
                        t,
                        "E210_CLOCK",
                        "Align series before combining different candle clocks",
                    )
                clock = next(iter(clocks), typ.clock or self.clock)
                if clock is not None and any(arg.account for arg in args):
                    self.fail(
                        t, "E210_CLOCK", "Account values use the primary candle clock"
                    )
                if clock != typ.clock:
                    typ = replace(typ, clock=clock)
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
        if op == "on_feed":
            name = str(c[0])
            if self.feed is None or self.feed.name != name:
                self.fail(t, "E210_CLOCK", f"Unknown secondary feed {name}")
            if self.clock is not None:
                self.fail(t, "E210_CLOCK", "Nested feed scopes are unavailable")
            self.clock = name
            try:
                native = sub(c[1])
            finally:
                self.clock = None
            if not native.type.series or native.type.clock != name:
                self.fail(
                    t,
                    "E210_CLOCK",
                    "A feed scope requires a series on its candle clock",
                )
            return replace(
                build("on_feed", name, [native], native.type),
                field_ready=native.field_ready,
            )
        if op == "align":
            native = sub(c[0])
            if (
                self.clock is not None
                or not native.type.series
                or native.type.clock is None
                or native.type.kind == "record"
            ):
                self.fail(
                    t,
                    "E210_CLOCK",
                    "Align a secondary numeric or Boolean series from primary scope",
                )
            return build(
                "align",
                native.type.clock,
                [native],
                replace(native.type, clock=None),
                0,
            )
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
                Type(
                    "boolean" if boolean else "numeric",
                    False,
                    unit,
                    scale="percent" if self.version >= 2 and op == "percent" else None,
                ),
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
                if name in self.unavailable_bindings:
                    raise UnavailableBinding(name)
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
            if self.clock is not None and e.type.series and e.type.clock != self.clock:
                self.fail(
                    t, "E210_CLOCK", f"Binding {name} uses a different candle clock"
                )
            self.used.add(name)
            return replace(
                build(
                    "parameter" if name in self.parameters else "let",
                    name,
                    [],
                    e.type,
                    e.ready,
                    e.constant,
                ),
                field_ready=e.field_ready,
            )
        if op == "postfix":
            self.nodes += len(c) - 1
            if depth + len(c) > 64 or self.nodes > 2048:
                self.fail(t, "E207_LIMIT", "Postfix chain exceeds expression limits")
            e = sub(c[0])
            for suffix in c[1:]:
                if suffix.data == "field":
                    field = str(suffix.children[0])
                    if field not in e.type.fields:
                        fields = e.type.fields
                        matches = difflib.get_close_matches(field, fields, n=1)
                        self.fail(
                            suffix,
                            "E204_SELECTOR",
                            f"Unknown field {field} for this expression",
                            f"Use .{matches[0]}"
                            if matches
                            else "Available fields are "
                            + ", ".join(f".{name}" for name in fields)
                            if fields
                            else "Select fields on a record such as MACD(12, 26, 9)",
                        )
                    ready = dict(e.field_ready)[field]
                    e = build("field", field, [e], e.type.field_type(field), ready)
                else:
                    if len(str(suffix.children[0])) > 6:
                        self.fail(suffix, "E205_OFFSET", "Maximum offset is 100000")
                    bars = int(suffix.children[0])
                    if (
                        not e.type.series
                        or (
                            e.type.kind != "numeric"
                            and not (self.version >= 2 and e.type.kind == "boolean")
                        )
                        or e.account
                        or bars > 100000
                    ):
                        self.fail(
                            suffix,
                            "E205_OFFSET",
                            "Offset requires market series and 0..100000 bars"
                            if self.version >= 2
                            else "Offset requires numeric market series and 0..100000 bars",
                        )
                    e = build("offset", bars, [e], e.type, e.ready + bars)
            return e
        if op == "function":
            return self.call(t, sub, build)
        args = [sub(x) for x in (c[::2] if op == "compare" else c)]
        a = args[0]
        b = args[-1]
        series = any(x.type.series for x in args)
        if op in {"available", "coalesce", "choose"}:
            if any(arg.type.kind == "record" for arg in args):
                self.fail(
                    t, "E203_TYPE", "Select a record field before testing availability"
                )
            if op == "available":
                return build("choice", op, args, Type("boolean", series), 0)
            if op == "choose" and a.type.kind != "boolean":
                self.fail(t, "E203_TYPE", "choose requires a Boolean condition")
            left, right = args[-2:]
            if (left.type.kind, left.type.unit) != (right.type.kind, right.type.unit):
                self.fail(
                    t, "E203_TYPE", f"{op} branches must have matching kinds and units"
                )
            ready = min(left.ready, right.ready)
            if op == "choose":
                ready = max(a.ready, ready)
            branch_scale = (
                left.type.scale if left.type.scale == right.type.scale else None
            )
            return build(
                "choice",
                op,
                args,
                Type(right.type.kind, series, right.type.unit, scale=branch_scale),
                ready,
            )
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
            if self.version >= 2 and {a.type.scale, b.type.scale} == {
                "points",
                "percent",
            }:
                threshold = a if a.type.scale == "percent" else b
                value = threshold.constant
                interpretation = (
                    "A percentage threshold is fractional."
                    if value is None
                    else f"This threshold is interpreted as {value:.15g} points."
                )
                points = value * 100 if value is not None else None
                suggestion = (
                    "Use a point threshold or divide the point series by 100"
                    if points is None or not math.isfinite(points)
                    else f"Use {points:.15g} for a point threshold or divide the point series by 100"
                )
                warning = Problem(
                    "W_POINT_SCALE",
                    interpretation + " This indicator is measured in points.",
                    threshold.span,
                    suggestion + " to compare with a fraction",
                ).diagnostic
                self.warnings.append({**warning, "severity": "warning"})
            elif (
                self.version == 1
                and any(x.op == "call" and x.value == "RSI" for x in args)
                and any(x.data == "percent" for x in (c[0], c[-1]))
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
        scale: Scale | None = None
        if self.version >= 2 and unit == RATIO:
            if symbol in "+-":
                if (
                    a.type.scale == b.type.scale
                    or b.type.scale is None
                    and not b.type.series
                ):
                    scale = a.type.scale
                elif a.type.scale is None and not a.type.series:
                    scale = b.type.scale
            elif symbol == "/" and a.type.scale == "points" and b.constant == 100:
                scale = "fraction"
        return build(
            "binary",
            symbol,
            args,
            Type("numeric", series, unit, scale=scale),
            constant=folded,
        )

    def call(self, t, sub, build):
        function = FUNCTIONS[str(t.children[0])]
        trees = t.children[1].children if len(t.children) > 1 else ()
        arguments = [
            Argument(
                sub(tree),
                str(tree.children[0]) if tree.data == "number" else None,
                tree.data == "typed_number" and tree.children[1] == "price",
            )
            for tree in trees
        ]

        def default_close():
            return build("builtin", "close", [], Type("numeric", True, PRICE))

        try:
            args = function.bind(
                arguments, default_close, static_periods=self.version >= 2
            )
        except InvalidCall as error:
            origin = t if error.argument is None else trees[error.argument]
            self.fail(origin, error.code, str(error))
        self.calls.add(t)
        if len(self.calls) > 128:
            self.fail(t, "E207_LIMIT", "More than 128 unique indicator calls")
        if function.requires_profile and self.version == 1:
            self.profile_calls.add(profile_key([arg.value for arg in args]))
            if len(self.profile_calls) > MAX_PROFILE_CALLS:
                self.fail(
                    t, "E207_LIMIT", "More than four distinct Volume Profile calls"
                )
        result = replace(
            build(
                "call",
                function.name,
                args,
                function.output_type(args, with_scale=self.version >= 2),
                function.readiness(args),
            ),
            field_ready=tuple(
                (field.name, function.field_ready(field.name, args))
                for field in function.fields
            ),
        )
        if function.requires_profile and result.type.clock is not None:
            self.fail(
                t,
                "E210_CLOCK",
                "Volume Profile uses the primary clock and its lower-timeframe input",
            )
        return result

    def parameter(self, tree):
        name = str(tree.children[0])
        kind = cast(ParameterKind, str(tree.children[1]))
        if (
            name in self.reserved
            or name in self.names
            or self.feed
            and name == self.feed.name
        ):
            self.fail(
                tree, "E103_DUPLICATE_BINDING", f"Reserved or duplicate name {name}"
            )
        if len(self.parameters) >= 128:
            self.fail(tree, "E207_LIMIT", "More than 128 parameters")
        expected_kind, unit = PARAMETER_KINDS[kind]

        def normalize(value, origin):
            if kind == "bool":
                if type(value) is bool:
                    return value
            elif type(value) in (int, float) and -float("inf") < value < float("inf"):
                if kind != "count":
                    return float(value)
                if 0 <= value <= 2**53 - 1 and float(value).is_integer():
                    return int(value)
            self.fail(
                origin,
                "E208_PARAMETER",
                f"Parameter {name} requires a finite {kind} value",
            )

        def constant(origin):
            expr = self.expr(origin)
            nodes = [expr]
            while nodes:
                node = nodes.pop()
                if node.op not in {"literal", "unary", "binary"}:
                    self.fail(
                        origin,
                        "E208_PARAMETER",
                        "Parameter declarations require independent constants",
                    )
                nodes.extend(node.args)
            compatible = (
                expr.type.unit == unit or kind == "count" and expr.type.unit == RATIO
            )
            if (
                expr.type.kind != expected_kind
                or not compatible
                or expr.constant is None
            ):
                self.fail(
                    origin,
                    "E208_PARAMETER",
                    f"Parameter {name} requires a {kind} constant",
                )
            return normalize(expr.constant, origin), expr.type.scale

        default, scale = constant(tree.children[2])
        minimum = maximum = None
        if len(tree.children) > 3:
            bounds = tree.children[3]
            if kind == "bool":
                self.fail(
                    bounds,
                    "E208_PARAMETER",
                    "Boolean parameters do not have numeric bounds",
                )
            minimum, maximum = (constant(bound)[0] for bound in bounds.children)
            if not minimum <= default <= maximum:
                self.fail(
                    bounds, "E208_PARAMETER", f"Default for {name} is outside its range"
                )
        value = normalize(self.overrides.get(name, default), tree)
        if minimum is not None and not minimum <= value <= maximum:
            self.fail(
                tree, "E208_PARAMETER", f"Override for {name} is outside its range"
            )
        span = self.span(tree)
        self.parameters[name] = Parameter(
            name, kind, default, value, minimum, maximum, span
        )
        self.names[name] = Expr(
            "parameter",
            name,
            (),
            Type(expected_kind, False, unit, scale=scale),
            0,
            span,
            value,
        )

    def binding(self, tree, count):
        name = str(tree.children[0])
        if (
            name in self.reserved
            or name in self.names
            or self.feed
            and name == self.feed.name
        ):
            self.fail(
                tree, "E103_DUPLICATE_BINDING", f"Reserved or duplicate name {name}"
            )
        if count >= 128:
            self.fail(tree, "E207_LIMIT", "More than 128 lets")
        expression = self.expr(tree.children[1])
        if expression.type.kind == "record" and self.version == 1:
            self.fail(tree, "E203_TYPE", "let requires a numeric or Boolean expression")
        self.names[name] = expression
        return name, expression, self.span(tree)

    @staticmethod
    def check_condition(expression):
        if expression.type.clock is not None:
            raise Problem(
                "E210_CLOCK",
                "Align a secondary series before using it in a rule",
                expression.span,
            )
        if expression.type.kind != "boolean":
            raise Problem(
                "E203_TYPE", "when requires a Boolean condition", expression.span
            )

    def sizing_value(self, tree, *, fixed=False, label="sizing"):
        expression = self.expr(tree.children[0], True)
        if expression.type.clock is not None:
            self.fail(
                tree,
                "E210_CLOCK",
                f"Align a secondary series before using it for {label}",
            )
        if expression.type.kind != "numeric" or expression.type.unit not in (
            (RATIO, MONEY) if fixed else (RATIO,)
        ):
            self.fail(tree, "E302_SIZING", f"Invalid {label} dimension")
        if expression.constant is not None and (
            expression.constant <= 0 or (not fixed and expression.constant > 1)
        ):
            self.fail(tree, "E302_SIZING", f"Invalid {label} amount")
        return expression

    def sizing(self, tree):
        if tree.data == "short_entry":
            tree = tree.children[0]
        fixed = tree.data == "fixed_money"
        stop_risk = tree.data == "stop_risk"
        expression = self.sizing_value(
            tree, fixed=fixed, label="risk fraction" if stop_risk else "sizing"
        )
        cap = (
            self.sizing_value(tree.children[1], label="allocation cap")
            if stop_risk and len(tree.children) > 1
            else None
        )
        return expression, fixed, cap

    def condition(self, tree):
        expression = self.expr(tree)
        self.check_condition(expression)
        return expression

    def sale_size(self, tree):
        if tree.data in ("sell_all", "cover_all"):
            return None
        fraction = tree.data in ("sell_fraction", "cover_fraction")
        expression = self.expr(tree.children[0])
        if expression.type.clock is not None:
            self.fail(
                tree,
                "E210_CLOCK",
                "Align a secondary series before using it for an exit quantity",
            )
        units = (RATIO,) if fraction else (RATIO, COUNT, VOLUME)
        if (
            expression.type.kind != "numeric"
            or expression.type.unit not in units
            or (not fraction and expression.type.scale is not None)
        ):
            self.fail(
                tree, "E302_SIZING", "Use a ratio of position or a base-unit quantity"
            )
        value = expression.constant
        if value is not None and (value <= 0 or (fraction and value > 1)):
            self.fail(tree, "E302_SIZING", "Invalid exit quantity")
        return SellSize("fraction" if fraction else "units", expression)

    def scale_rule(self, tree):
        condition, sizing = tree.children
        fixed = sizing.data == "fixed_money"
        return ScaleRule(
            self.condition(condition),
            self.sizing_value(sizing, fixed=fixed, label="add size"),
            fixed,
            self.span(tree),
        )

    def quantity_step(self, tree):
        value = float(tree.children[0])
        if not math.isfinite(value) or value <= 0:
            self.fail(tree, "E302_SIZING", "Quantity step must be positive and finite")
        return value

    def exit_rule(self, tree):
        name = str(tree.children[0])
        sale = self.sale_size(tree.children[2]) if len(tree.children) == 3 else None
        if tree.data == "market_exit":
            return ExitRule(
                name,
                self.span(tree),
                condition=self.condition(tree.children[1]),
                sale=sale,
            )
        count = self.expr(tree.children[1])
        value = count.constant
        if (
            count.type.kind != "numeric"
            or count.type.unit not in (COUNT, RATIO)
            or count.type.scale is not None
            or value is None
            or not float(value).is_integer()
            or not 1 <= value <= 1_000_000
        ):
            self.fail(
                tree.children[1],
                "E203_TYPE",
                "A time exit needs a static count from 1 through 1,000,000 bars",
                "Use a whole number or a count parameter",
            )
        return ExitRule(name, self.span(tree), after_bars=int(value), sale=sale)

    def ordered_exit(self, trees):
        if len(trees) > 16:
            self.fail(
                trees[16], "E207_LIMIT", "At most 16 ordered exit rules are supported"
            )
        rules: dict[str, ExitRule] = {}
        for tree in trees:
            rule = self.exit_rule(tree)
            if rule.name in rules:
                self.fail(
                    tree,
                    "E103_DUPLICATE_BINDING",
                    f"Duplicate exit rule name {rule.name}",
                )
            rules[rule.name] = rule
        return tuple(rules.values())

    def protection(self, tree):
        expression = self.expr(tree.children[0])
        if expression.type.clock is not None:
            self.fail(
                tree,
                "E210_CLOCK",
                "Align a secondary series before using it for protection",
            )
        if (
            expression.type.kind != "numeric"
            or expression.type.unit not in (RATIO, PRICE)
            or (
                expression.constant is not None
                and (
                    expression.constant <= 0
                    or (
                        tree.data in ("stop", "trail")
                        and expression.type.unit == RATIO
                        and expression.constant >= 1
                    )
                )
            )
        ):
            self.fail(tree, "E303_RISK", "Invalid risk distance")
        return expression

    def backtest_config(self, tree):
        w, capital, fee, slip, _, calendar = tree.children[:6]
        a, b = map(str, w.children)
        try:
            if (
                date.fromisoformat(a) > date.fromisoformat(b)
                or date.fromisoformat(b) == date.max
            ):
                raise ValueError()
        except ValueError:
            self.fail(w, "E402_WINDOW", "Invalid inclusive date window")
        config = Config(
            a,
            b,
            float(capital.children[0]),
            str(capital.children[1]),
            float(fee.children[0]) / 10000,
            float(slip.children[0]) / 10000,
            calendar=str(calendar.children[0]) if calendar.children else "24x7",
        )
        if (
            not math.isfinite(config.capital)
            or config.capital <= 0
            or max(config.fee_rate, config.slippage_rate) >= 1
        ):
            self.fail(tree, "E302_SIZING", "Invalid capital or cost rate")
        return config

    def short_margin(self, tree):
        initial, maintenance, borrow = map(float, tree.children)
        terms = ShortMargin(initial / 100, maintenance / 100, borrow / 10000)
        if (
            not 0 < terms.maintenance_rate < terms.initial_rate <= 1
            or not 0 <= terms.borrow_rate_per_day < 1
            or borrow > 0
            and terms.borrow_rate_per_day == 0
        ):
            self.fail(
                tree,
                "E304_MARGIN",
                "Use 0 < maintenance margin < initial margin <= 100% and a borrow rate below 10,000 bps per day",
            )
        return terms

    def order_expiry(self, execution):
        if not execution.children:
            return None
        expiry = execution.children[0]
        label = str(expiry.children[0])
        if len(label) > 7 or seconds(label) > 604800:
            self.fail(expiry, "E207_LIMIT", "Order expiry can be at most seven days")
        return seconds(label)

    def editor_errors(self, first):
        """Check independently recoverable sections against their original source spans."""
        errors = [first]
        seen = {(first["code"], (first["span"] or {}).get("start_byte"))}

        def add(problem):
            item = problem.diagnostic
            key = item["code"], (item["span"] or {}).get("start_byte")
            if key not in seen and len(errors) < MAX_EDITOR_ERRORS:
                errors.append(item)
                seen.add(key)

        def check(validate, *args):
            try:
                validate(*args)
                return True
            except UnavailableBinding:
                return False
            except Problem as problem:
                add(problem)
                return False

        if first["code"] != "E207_LIMIT":
            try:
                sections = parser(self.version).parse(self.text).children
            except UnexpectedInput:
                sections = self.recover_sections(first, add)
            self.declared = {
                section if isinstance(section, str) else str(section.children[0])
                for section in sections
                if isinstance(section, str)
                or section.data in ("param_decl", "let_decl")
            }
            count = 0
            for section in sections:
                if len(errors) >= MAX_EDITOR_ERRORS or self.nodes >= 2048:
                    break
                if isinstance(section, str):
                    if section not in self.names:
                        self.unavailable_bindings.add(section)
                elif section.data in ("param_decl", "let_decl"):
                    name = str(section.children[0])
                    valid = (
                        check(self.parameter, section)
                        if section.data == "param_decl"
                        else check(self.binding, section, count)
                    )
                    count += int(valid and section.data == "let_decl")
                    if not valid and name not in self.names:
                        self.unavailable_bindings.add(name)
                elif section.data == "feed_decl":
                    check(self.declare_feed, section)
                elif section.data in ("entry", "exit"):
                    if section.data == "exit" and section.children[0].data in (
                        "market_exit",
                        "timed_exit",
                    ):
                        for rule in section.children[:16]:
                            if len(errors) < MAX_EDITOR_ERRORS:
                                check(self.exit_rule, rule)
                    else:
                        check(self.condition, section.children[0])
                        if section.data == "exit" and len(section.children) == 2:
                            check(self.sale_size, section.children[1])
                    if section.data == "entry" and len(errors) < MAX_EDITOR_ERRORS:
                        check(self.sizing, section.children[1])
                elif section.data == "scale":
                    check(self.scale_rule, section)
                elif section.data == "risk":
                    for child in section.children:
                        if (
                            child.data != "max_positions"
                            and len(errors) < MAX_EDITOR_ERRORS
                        ):
                            check(
                                self.quantity_step
                                if child.data == "quantity_step"
                                else self.protection,
                                child,
                            )
                elif section.data == "backtest":
                    check(self.backtest_config, section)
                    check(self.order_expiry, section.children[4])
                    if len(section.children) == 7:
                        check(self.short_margin, section.children[6])
        return sorted(
            errors, key=lambda item: (item["span"] or {}).get("start_byte", -1)
        )

    def recover_sections(self, first, add):
        sections = []
        matches = [
            match
            for match in EDITOR_SECTIONS.finditer(self.text)
            if (match[1] != "param" or self.version >= 2)
            and (match[1] != "feed" or self.version >= 3)
            and (match[3] != "scale" or self.version >= 6)
        ][: MAX_EDITOR_SECTIONS + 1]
        start_byte = (first["span"] or {}).get("start_byte", -1)
        for index, match in enumerate(matches[:MAX_EDITOR_SECTIONS]):
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(self.text)
            )
            rule = f"{match[1]}_decl" if match[1] else match[3]
            try:
                sections.append(
                    editor_parser(self.version).parse(
                        TextSlice(self.text, match.start(), end), start=rule
                    )
                )
            except UnexpectedInput as error:
                if not self.bytes[match.start()] <= start_byte <= self.bytes[end]:
                    add(self.syntax_problem(error, end_of_section=end))
                if match[2] is not None:
                    sections.append(match[2])
        return sections

    def declare_feed(self, tree):
        name, period, age = map(str, tree.children)
        if name in self.reserved or len(name) > 64:
            self.fail(tree, "E103_DUPLICATE_BINDING", f"Reserved feed name {name}")
        if any(len(value) > 7 or seconds(value) > 604800 for value in (period, age)):
            self.fail(
                tree,
                "E210_CLOCK",
                "Feed timeframe and max_age must fit within seven days",
            )
        self.feed = Feed(name, seconds(period), seconds(age), self.span(tree))

    def compile(self):
        try:
            tree = parser(self.version).parse(self.text)
        except UnexpectedInput as exc:
            raise self.syntax_problem(exc) from exc
        self.declared = {
            str(t.children[0])
            for t in tree.children
            if t.data in {"let_decl", "param_decl"}
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
        if "feed_decl" in blocks:
            self.declare_feed(blocks["feed_decl"])
        for declaration in tree.children:
            if declaration.data == "param_decl":
                self.parameter(declaration)
        unknown_overrides = self.overrides.keys() - self.parameters.keys()
        if unknown_overrides:
            raise Problem(
                "E208_PARAMETER", f"Unknown parameter {min(unknown_overrides)}"
            )
        for t in tree.children:
            if t.data == "let_decl":
                bindings.append(self.binding(t, len(bindings)))
        entry = self.expr(children("entry")[0])
        exit_trees = children("exit")
        sizing_tree = children("entry")[1]
        is_short = sizing_tree.data == "short_entry"
        if is_short:
            sizing_tree = sizing_tree.children[0]
        if self.version >= 8:
            side_prefix = "cover_" if is_short else "sell_"
            actions = (
                [tree.children[2] for tree in exit_trees]
                if exit_trees[0].data in ("market_exit", "timed_exit")
                else exit_trees[1:]
            )
            for action in actions:
                if not action.data.startswith(side_prefix):
                    self.fail(
                        action,
                        "E304_MARGIN",
                        "Use cover to close a short or sell to close a long",
                    )
        exit_rules: tuple[ExitRule, ...] = ()
        sale = None
        if exit_trees[0].data in ("market_exit", "timed_exit"):
            exit_expr = None
            self.check_condition(entry)
            exit_rules = self.ordered_exit(exit_trees)
        else:
            exit_expr = self.expr(exit_trees[0])
            for expression in (entry, exit_expr):
                self.check_condition(expression)
            if len(exit_trees) == 2:
                sale = self.sale_size(exit_trees[1])
        spans["sizing"] = self.span(sizing_tree).model_dump()
        sizing, fixed, cap = self.sizing(sizing_tree)
        stop_risk = sizing_tree.data == "stop_risk"
        rules = {}
        step = None
        if "risk" in blocks and not children("risk"):
            self.fail(blocks["risk"], "E303_RISK", "Empty risk section")
        for t in children("risk") if "risk" in blocks else []:
            if t.data == "max_positions":
                continue
            if t.data == "quantity_step":
                step = self.quantity_step(t)
                continue
            e = self.protection(t)
            spans[str(t.data)] = self.span(t).model_dump()
            rules[str(t.data)] = e
        if stop_risk and "stop" not in rules:
            self.fail(
                sizing_tree, "E302_SIZING", "Stop-based sizing requires a stop loss"
            )
        if "trail" in rules and "stop" not in rules:
            raise Problem(
                "E303_RISK",
                "A trailing stop requires an initial stop loss",
                rules["trail"].span,
            )
        cfg = self.backtest_config(blocks["backtest"])
        short_terms = children("backtest")[6:]
        if is_short != bool(short_terms):
            self.fail(
                short_terms[0] if short_terms else blocks["backtest"],
                "E304_MARGIN",
                "A short requires initial margin, maintenance margin, and a borrow rate. A long uses cash sizing",
            )
        if is_short and "scale" in blocks:
            self.fail(
                blocks["scale"],
                "E302_SIZING",
                "Scaling is available for long positions",
            )
        short_margin = self.short_margin(short_terms[0]) if short_terms else None
        scale = self.scale_rule(blocks["scale"]) if "scale" in blocks else None
        if (
            scale is not None
            and scale.fixed
            and children("scale")[1].children[1] != cfg.currency
        ):
            self.fail(
                blocks["scale"],
                "E302_SIZING",
                "Add sizing currency differs from capital",
            )
        order_max_age = self.order_expiry(children("backtest")[4])
        if fixed and sizing_tree.children[1] != cfg.currency:
            self.fail(
                sizing_tree, "E302_SIZING", "Sizing currency differs from capital"
            )
        duration = None
        if "timeframe" in blocks:
            label = str(children("timeframe")[0])
            if len(label) > 7:
                self.fail(
                    blocks["timeframe"], "E207_LIMIT", "Maximum timeframe is seven days"
                )
            duration = seconds(label)
            if duration > 604800:
                self.fail(
                    blocks["timeframe"], "E207_LIMIT", "Maximum timeframe is seven days"
                )
            if self.feed is not None and (
                self.feed.seconds <= duration
                or (
                    self.feed.seconds % duration
                    and not (cfg.calendar == "session" and self.feed.seconds == 86400)
                )
            ):
                self.fail(
                    blocks["feed_decl"],
                    "E210_CLOCK",
                    f"Feed {self.feed.name} must use a larger exact multiple of the primary timeframe",
                )
        try:
            name = json.loads(children("header")[0])
        except ValueError:
            self.fail(blocks["header"], "E101_SYNTAX", "Invalid JSON string")
        if not 1 <= len(name) <= 120 or not name.isprintable():
            self.fail(blocks["header"], "E101_SYNTAX", "Invalid strategy name")
        strategy = Strategy(
            self.raw,
            name,
            str(children("market")[0]) if "market" in blocks else None,
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
            self.version,
            tuple(self.parameters.values()),
            tuple(
                (name, self.parameters[name].value) for name in sorted(self.overrides)
            ),
            feed=self.feed,
            stop_risk=stop_risk,
            allocation_cap=cap,
            exit_rules=exit_rules,
            trail=rules.get("trail"),
            order_max_age_seconds=order_max_age,
            sale=sale,
            quantity_step=step,
            scale=scale,
            short_margin=short_margin,
        )
        if self.version >= 2:
            reachable = {node.value for node in strategy.graph() if node.op == "let"}
            if (
                len(
                    {
                        profile_key([arg.value for arg in call.args])
                        for call in strategy.calls("VPROFILE")
                    }
                )
                > MAX_PROFILE_CALLS
            ):
                raise Problem(
                    "E207_LIMIT", "More than four reachable Volume Profile calls"
                )
        else:
            reachable = self.used
        for label, _, span in bindings:
            if label not in reachable:
                tail = (
                    " does not affect warmup"
                    if self.version >= 2
                    else " counts toward warmup"
                )
                d = Problem(
                    "W_UNUSED_LET", f"Unused let {label}{tail}", span
                ).diagnostic
                self.warnings.append({**d, "severity": "warning"})
        return replace(strategy, warnings=tuple(self.warnings))


def compile_source(
    source: bytes | str, *, parameters: Mapping[str, ParameterValue] | None = None
) -> Strategy | PortfolioSpec:
    try:
        raw = source.encode() if isinstance(source, str) else source
        if is_portfolio_source(raw):
            from .portfolio import compile_portfolio

            if parameters:
                raise Problem("E305_PORTFOLIO", "Set parameter overrides on each asset")
            return compile_portfolio(raw)
        return Compiler(raw, parameters).compile()
    except UnicodeError as exc:
        raise Problem("E101_SYNTAX", "Expected UTF-8 source") from exc
    except (RecursionError, OverflowError) as exc:
        raise Problem("E207_LIMIT", "Expression exceeds compiler limits") from exc
