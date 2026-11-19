"""Immutable expression graph and its public, versioned representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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

    def public(self):
        result: dict[str, Any] = {
            "kind": self.kind,
            "shape": "series" if self.series else "scalar",
        }
        if self.kind == "numeric":
            result["dimension"] = dimension(self.unit)
        if self.kind == "record":
            result["fields"] = {
                k: Type("numeric", True, self.unit).public() for k in self.fields
            }
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

    def public(self, path):
        children = self.args

        def child(i, key):
            return children[i].public(f"{path}.{key}")

        match self.op:
            case "literal":
                kind = "Literal"
                fields = dict(
                    value=self.value,
                    dimension=dimension(self.type.unit)
                    if self.type.kind == "numeric"
                    else None,
                )
            case "builtin" | "let" | "account":
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
            case "call":
                kind = "Call"
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
            case _:
                raise AssertionError(self.op)
        return dict(
            kind=kind,
            node_id=path,
            span=self.span.model_dump(),
            inferred_type=self.type.public(),
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
class Strategy:
    source: bytes
    name: str
    symbol: str
    seconds: int
    bindings: tuple
    entry: Expr
    exit: Expr
    sizing: Expr
    fixed: bool
    stop: Expr | None
    target: Expr | None
    config: Config
    spans: dict
    warnings: tuple

    @property
    def warmup(self):
        return max(e.ready for e in self.roots() if e is not None)

    def roots(self):
        return [e for _, e, _ in self.bindings] + [
            self.entry,
            self.exit,
            self.sizing,
            self.stop,
            self.target,
        ]

    def public(self):
        def risk(e, path):
            return (
                dict(
                    expression=e.public("risk." + path + ".expression"),
                    mode="price" if e.type.unit == PRICE else "ratio",
                    span=self.spans[path],
                )
                if e
                else None
            )

        sizing = dict(
            kind="fixed_money" if self.fixed else "equity_fraction",
            expression=self.sizing.public("entry.sizing.expression"),
            span=self.spans["sizing"],
        )
        if self.fixed:
            sizing["currency"] = self.config.currency
        return dict(
            schema_version=1,
            dsl_version=1,
            name=self.name,
            symbol=self.symbol,
            timeframe_seconds=self.seconds,
            bindings=[
                dict(
                    name=n,
                    expression=e.public(f"bindings.{i}.expression"),
                    span=s.model_dump(),
                )
                for i, (n, e, s) in enumerate(self.bindings)
            ],
            entry=dict(
                condition=self.entry.public("entry.condition"),
                sizing=sizing,
                span=self.spans["entry"],
            ),
            exit=dict(
                condition=self.exit.public("exit.condition"),
                action="sell_all",
                span=self.spans["exit"],
            ),
            risk=dict(
                stop=risk(self.stop, "stop"),
                target=risk(self.target, "target"),
                max_open_positions=1,
            ),
            backtest=dict(**asdict(self.config), span=self.spans["backtest"]),
            span=self.spans["start"],
        )
