"""Immutable expression graph and its public, versioned representation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Span(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_byte: int
    end_byte: int


class Problem(ValueError):
    def __init__(
        self, code, message, span=None, suggestion=None, row=None, *, details=None
    ):
        super().__init__(message)
        self.diagnostic = dict(
            code=code,
            message=message,
            severity="error",
            span=span.model_dump() if span else None,
            suggestion=suggestion,
            data_row=row,
            node_id=None,
            details={} if details is None else details,
        )


RATIO = (0, 0)
PRICE = (1, -1)
MONEY = (1, 0)
VOLUME = (0, 1)
COUNT = "count"
UNITS = {
    "ratio": RATIO,
    "price": PRICE,
    "volume": VOLUME,
    "money": MONEY,
    "count": COUNT,
}
ParameterKind = Literal["count", "ratio", "price", "bool"]
ParameterValue = bool | int | float
Scale = Literal["points", "fraction", "percent"]
PARAMETER_KINDS: dict[str, tuple[str, Any]] = {
    "count": ("numeric", COUNT),
    "ratio": ("numeric", RATIO),
    "price": ("numeric", PRICE),
    "bool": ("boolean", RATIO),
}


def dimension(unit):
    return (
        {"kind": "count"}
        if unit == COUNT
        else {"kind": "powers", "quote": unit[0], "base": unit[1]}
    )


@dataclass(frozen=True)
class Type:
    kind: str = "numeric"
    series: bool = False
    unit: Any = RATIO
    fields: tuple = ()
    field_units: tuple[tuple[str, Any], ...] = ()
    scale: Scale | None = None
    field_scales: tuple[tuple[str, Scale], ...] = ()
    clock: str | None = None

    def field_type(self, name: str) -> Type:
        return Type(
            "numeric",
            True,
            dict(self.field_units).get(name, self.unit),
            scale=dict(self.field_scales).get(name),
            clock=self.clock,
        )

    def public(self):
        result: dict[str, Any] = {
            "kind": self.kind,
            "shape": "series" if self.series else "scalar",
        }
        if self.kind == "numeric":
            result["dimension"] = dimension(self.unit)
            if self.scale is not None:
                result["scale"] = self.scale
        if self.kind == "record":
            result["fields"] = {k: self.field_type(k).public() for k in self.fields}
        if self.clock is not None:
            result["clock"] = self.clock
        return result


@dataclass(frozen=True, eq=False)
class Expr:
    op: str
    value: Any
    args: tuple[Expr, ...]
    type: Type
    ready: int
    span: Span
    constant: Any = None
    account: bool = False
    field_ready: tuple[tuple[str, int], ...] = ()

    def children(self):
        labels = {
            "bool": (f"operands.{i}" for i in range(len(self.args))),
            "call": (f"arguments.{i}" for i in range(len(self.args))),
            "choice": (f"arguments.{i}" for i in range(len(self.args))),
            "field": ("base",),
            "offset": ("base",),
            "unary": ("operand",),
            "on_feed": ("expression",),
            "align": ("expression",),
        }.get(self.op, ("left", "right"))
        return zip(labels, self.args)

    def public(self, path, version=1):
        children = self.args

        def child(i, key):
            return children[i].public(f"{path}.{key}", version)

        match self.op:
            case "literal":
                kind = "Literal"
                fields = dict(
                    value=self.value,
                    dimension=dimension(self.type.unit)
                    if self.type.kind == "numeric"
                    else None,
                )
            case "builtin" | "let" | "account" | "parameter":
                kind = "Reference"
                fields = dict(name=self.value, binding_kind=self.op)
            case "unary":
                kind = "Unary"
                fields = dict(operator=self.value, operand=child(0, "operand"))
            case "binary" | "compare" | "cross":
                kind = {"binary": "Binary", "compare": "Compare", "cross": "Cross"}[
                    self.op
                ]
                fields = {
                    "direction" if self.op == "cross" else "operator": self.value,
                    "left": child(0, "left"),
                    "right": child(1, "right"),
                }
            case "bool":
                kind = "Boolean"
                fields = dict(
                    operator=self.value,
                    operands=[child(i, f"operands.{i}") for i in range(len(children))],
                )
            case "call" | "choice":
                kind = "Call" if self.op == "call" else "Choice"
                fields = dict(
                    function=self.value,
                    arguments=[
                        child(i, f"arguments.{i}") for i in range(len(children))
                    ],
                )
            case "field" | "offset":
                kind = "Field" if self.op == "field" else "Lookback"
                fields = {
                    "base": child(0, "base"),
                    "field" if self.op == "field" else "bars": self.value,
                }
            case "on_feed" | "align":
                kind = "OnFeed" if self.op == "on_feed" else "Align"
                fields = dict(feed=self.value, expression=child(0, "expression"))
            case _:
                raise AssertionError(self.op)
        inferred = self.type.public()
        if version >= 2 and self.field_ready:
            inferred["field_readiness"] = dict(self.field_ready)
        return dict(
            kind=kind,
            node_id=path,
            span=self.span.model_dump(),
            inferred_type=inferred,
            **fields,
        )


@dataclass(frozen=True)
class Config:
    from_date: str
    to_date: str
    capital: float
    currency: str
    fee_rate: float
    slippage_rate: float
    execution: str = "next_bar_open"
    calendar: str = "24x7"


@dataclass(frozen=True)
class ShortMargin:
    initial_rate: float
    maintenance_rate: float
    borrow_rate_per_day: float


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: ParameterKind
    default: ParameterValue
    value: ParameterValue
    minimum: ParameterValue | None
    maximum: ParameterValue | None
    span: Span

    def public(self):
        return dict(
            name=self.name,
            kind=self.kind,
            default=self.default,
            value=self.value,
            minimum=self.minimum,
            maximum=self.maximum,
            span=self.span.model_dump(),
        )


@dataclass(frozen=True)
class Feed:
    name: str
    seconds: int
    max_age_seconds: int
    span: Span

    def public(self):
        return dict(
            name=self.name,
            role="higher_timeframe",
            timeframe_seconds=self.seconds,
            max_age_seconds=self.max_age_seconds,
            span=self.span.model_dump(),
        )


@dataclass(frozen=True)
class SellSize:
    kind: Literal["fraction", "units"]
    expression: Expr

    def public(self, path, version):
        return dict(
            kind=self.kind,
            expression=self.expression.public(path + ".expression", version),
        )


@dataclass(frozen=True)
class ScaleRule:
    condition: Expr
    sizing: Expr
    fixed: bool
    span: Span

    def public(self, version, currency):
        sizing = dict(
            kind="fixed_money" if self.fixed else "cash_fraction",
            expression=self.sizing.public("scale.sizing.expression", version),
        )
        if self.fixed:
            sizing["currency"] = currency
        return dict(
            condition=self.condition.public("scale.condition", version),
            sizing=sizing,
            span=self.span.model_dump(),
        )


@dataclass(frozen=True)
class ExitRule:
    name: str
    span: Span
    condition: Expr | None = None
    after_bars: int | None = None
    sale: SellSize | None = None

    def predicate(self, value: Callable[[Expr], float | None], held_closes: int):
        if self.condition is not None:
            result = value(self.condition)
            return result == 1 if result is not None else None
        assert self.after_bars is not None
        return held_closes >= self.after_bars

    def public(self, index: int, version: int):
        item = {
            "name": self.name,
            "span": self.span.model_dump(),
            **(
                {
                    "condition": self.condition.public(
                        f"exit.rules.{index}.condition", version
                    )
                }
                if self.condition is not None
                else {"after_bars": self.after_bars}
            ),
        }
        if version >= 6:
            item["action"] = (
                self.sale.public(f"exit.rules.{index}.action", version)
                if self.sale
                else {"kind": "all"}
            )
        return item


@dataclass(frozen=True)
class Strategy:
    source: bytes
    name: str
    symbol: str | None
    seconds: int | None
    bindings: tuple
    entry: Expr
    exit: Expr | None
    sizing: Expr
    fixed: bool
    stop: Expr | None
    target: Expr | None
    config: Config
    spans: dict
    warnings: tuple
    version: Literal[1, 2, 3, 4, 5, 6, 7, 8] = 1
    parameters: tuple[Parameter, ...] = ()
    parameter_overrides: tuple[tuple[str, ParameterValue], ...] = ()
    declared_config: Config | None = None
    run_settings: dict | None = None
    settings_origins: dict | None = None
    feed: Feed | None = None
    stop_risk: bool = False
    allocation_cap: Expr | None = None
    exit_rules: tuple[ExitRule, ...] = ()
    trail: Expr | None = None
    order_max_age_seconds: int | None = None
    sale: SellSize | None = None
    quantity_step: float | None = None
    scale: ScaleRule | None = None
    short_margin: ShortMargin | None = None

    @property
    def manages_quantity(self):
        return (
            self.short_margin is not None
            or self.sale is not None
            or self.scale is not None
            or self.quantity_step is not None
            or any(rule.sale is not None for rule in self.exit_rules)
        )

    @property
    def requires_feed(self):
        return self.feed is not None and any(
            node.op == "align" for node in self.graph()
        )

    @property
    def warmup(self):
        return max(e.ready for _, e in self.named_roots(warmup=True) if e is not None)

    def roots(self):
        return [expression for _, expression in self.named_roots()]

    def named_roots(self, *, warmup=False):
        prefix = (
            [(f"let {name}", expr) for name, expr, _ in self.bindings]
            if self.version == 1
            else []
        )
        named = prefix + [
            ("entry condition", self.entry),
            ("exit condition", self.exit),
            ("entry sizing", self.sizing),
            ("entry allocation cap", self.allocation_cap),
            ("stop loss", self.stop),
            ("take profit", self.target),
        ]
        if not warmup:
            named.extend(
                (f"exit rule {rule.name}", rule.condition) for rule in self.exit_rules
            )
            if self.trail is not None:
                named.append(("trailing stop", self.trail))
            if self.sale is not None:
                named.append(("exit quantity", self.sale.expression))
            named.extend(
                (f"exit rule {rule.name} quantity", rule.sale.expression)
                for rule in self.exit_rules
                if rule.sale is not None
            )
            if self.scale is not None:
                named.extend(
                    (
                        ("scale condition", self.scale.condition),
                        ("scale sizing", self.scale.sizing),
                    )
                )
        return named

    def graph(self):
        definitions = {name: expr for name, expr, _ in self.bindings}
        pending = self.roots()
        seen = set()
        while pending:
            node = pending.pop()
            if node is None or node in seen:
                continue
            seen.add(node)
            yield node
            pending.extend(node.args)
            if node.op == "let":
                pending.append(definitions[node.value])

    def calls(self, name: str):
        for node in self.graph():
            if node.op == "call" and node.value == name:
                yield node

    def public(self):
        def risk(e, path):
            return (
                dict(
                    expression=e.public("risk." + path + ".expression", self.version),
                    mode="price" if e.type.unit == PRICE else "ratio",
                    span=self.spans[path],
                )
                if e
                else None
            )

        sizing = dict(
            kind="fixed_money" if self.fixed else "equity_fraction",
            expression=self.sizing.public("entry.sizing.expression", self.version),
            span=self.spans["sizing"],
        )
        if self.fixed:
            sizing["currency"] = self.config.currency
        if self.stop_risk:
            sizing["kind"] = "stop_risk"
            sizing["allocation_cap"] = (
                self.allocation_cap.public("entry.sizing.allocation_cap", self.version)
                if self.allocation_cap is not None
                else None
            )
        exit = dict(action="sell_all", span=self.spans["exit"])
        if self.exit is not None:
            exit["condition"] = self.exit.public("exit.condition", self.version)
        else:
            exit["rules"] = [
                rule.public(index, self.version)
                for index, rule in enumerate(self.exit_rules)
            ]
        spec = dict(
            schema_version=self.version,
            dsl_version=self.version,
            name=self.name,
            symbol=self.symbol,
            timeframe_seconds=self.seconds,
            bindings=[
                dict(
                    name=n,
                    expression=e.public(f"bindings.{i}.expression", self.version),
                    span=s.model_dump(),
                )
                for i, (n, e, s) in enumerate(self.bindings)
            ],
            entry=dict(
                condition=self.entry.public("entry.condition", self.version),
                sizing=sizing,
                span=self.spans["entry"],
            ),
            exit=exit,
            risk=dict(
                stop=risk(self.stop, "stop"),
                target=risk(self.target, "target"),
                max_open_positions=1,
            ),
            backtest=dict(
                **asdict(self.declared_config or self.config),
                span=self.spans["backtest"],
            ),
            span=self.spans["start"],
        )
        if self.version >= 2:
            spec["requires_profile"] = next(self.calls("VPROFILE"), None) is not None
            spec["parameters"] = [
                parameter.public()
                for parameter in sorted(self.parameters, key=lambda value: value.name)
            ]
        if self.version >= 3:
            spec["feeds"] = [self.feed.public()] if self.feed is not None else []
            spec["required_feeds"] = (
                [self.feed.name] if self.feed is not None and self.requires_feed else []
            )
        if self.version >= 5:
            spec["risk"]["trail"] = risk(self.trail, "trail")
            spec["backtest"]["order_max_age_seconds"] = self.order_max_age_seconds
        if self.version >= 6:
            if self.exit is None:
                exit.pop("action")
            else:
                exit["action"] = (
                    self.sale.public("exit.action", self.version)
                    if self.sale
                    else {"kind": "all"}
                )
            spec["risk"]["quantity_step"] = self.quantity_step
            spec["scale"] = (
                self.scale.public(self.version, self.config.currency)
                if self.scale
                else None
            )
        if self.version >= 8:
            spec["entry"]["direction"] = "short" if self.short_margin else "long"
            spec["short_margin"] = (
                asdict(self.short_margin) if self.short_margin else None
            )
        return spec
