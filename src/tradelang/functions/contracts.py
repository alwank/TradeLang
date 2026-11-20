"""Typed and lexical contracts for built-in calls, independent of the parser."""

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..model import COUNT, PRICE, RATIO, VOLUME, Expr, Type

Role = Literal["source", "period", "multiplier"]
Readiness = Callable[[Sequence[Expr]], int]
UnitRule = Literal["source", "price", "ratio"]
MissingPolicy = Literal["window", "reseed", "interval"]


@dataclass(frozen=True)
class Argument:
    expression: Expr
    bare_number: str | None


@dataclass(frozen=True)
class Signature:
    roles: tuple[Role, ...]
    implicit_close: bool = False

    @property
    def canonical_roles(self) -> tuple[Role, ...]:
        return ("source", *self.roles) if self.implicit_close else self.roles


@dataclass(frozen=True)
class Field:
    name: str
    readiness: Readiness | None = None


@dataclass(frozen=True)
class KernelContext:
    columns: Mapping[str, Any]
    invalid_counts: MutableMapping[str, int]


Kernel = Callable[[Sequence[Any], KernelContext], Any]


class InvalidCall(Exception):
    def __init__(self, code: str, message: str, argument: int | None = None):
        super().__init__(message)
        self.code = code
        self.argument = argument


@dataclass(frozen=True)
class Function:
    name: str
    signatures: tuple[Signature, ...]
    unit: UnitRule
    readiness: Readiness
    missing: MissingPolicy
    kernel: Kernel
    fields: tuple[Field, ...] = ()
    required_columns: tuple[str, ...] = ()
    validate: Callable[[Sequence[Expr]], None] | None = None
    scale: Literal["points", "fraction"] | None = None

    def bind(
        self, arguments: Sequence[Argument], default_close: Callable[[], Expr]
    ) -> tuple[Expr, ...]:
        if any(arg.expression.account for arg in arguments):
            raise InvalidCall(
                "E203_TYPE", "Indicator inputs cannot depend on account state"
            )
        signature = next(
            (s for s in self.signatures if len(s.roles) == len(arguments)), None
        )
        if signature is None:
            raise InvalidCall("E203_TYPE", f"{self.name} has incorrect arity")
        normalized = [default_close()] if signature.implicit_close else []
        for index, (arg, role) in enumerate(
            zip(arguments, signature.roles, strict=True)
        ):
            expr = arg.expression
            if role == "source" and (
                expr.type.kind != "numeric"
                or not expr.type.series
                or expr.type.unit not in (RATIO, PRICE, VOLUME)
            ):
                raise InvalidCall(
                    "E203_TYPE", "Indicator requires a price, volume or ratio series"
                )
            if role == "period":
                if (
                    arg.bare_number is None
                    or not arg.bare_number.isdigit()
                    or not 1 <= expr.value <= 10000
                ):
                    raise InvalidCall(
                        "E202_PERIOD",
                        "Period must be an integer literal from 1 to 10000",
                        index,
                    )
                expr = replace(expr, type=Type(unit=COUNT))
            if role == "multiplier" and (
                arg.bare_number is None or not 0 < expr.value <= 10
            ):
                raise InvalidCall(
                    "E203_TYPE", "Band multiplier must be a positive literal at most 10"
                )
            normalized.append(expr)
        if self.validate is not None:
            self.validate(normalized)
        return tuple(normalized)

    def output_type(self, arguments: Sequence[Expr]) -> Type:
        unit = (
            arguments[0].type.unit
            if self.unit == "source"
            else (PRICE if self.unit == "price" else RATIO)
        )
        return Type(
            "record" if self.fields else "numeric",
            True,
            unit,
            tuple(field.name for field in self.fields),
        )

    def field_ready(self, name: str, arguments: Sequence[Expr]) -> int:
        field = next(field for field in self.fields if field.name == name)
        return (field.readiness or self.readiness)(arguments)
