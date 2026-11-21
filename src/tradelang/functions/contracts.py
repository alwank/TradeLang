"""Typed and lexical contracts for built-in calls, independent of the parser."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

from ..model import COUNT, PRICE, RATIO, UNITS, VOLUME, Expr, Type

if TYPE_CHECKING:
    from .profile import ProfileWindow

Role = Literal["source", "period", "multiplier", "number", "price_literal"]
Readiness = Callable[[Sequence[Expr]], int]
UnitRule = Literal["source", "price", "ratio", "volume"]
MissingPolicy = Literal["window", "reseed", "interval"]


@dataclass(frozen=True)
class Argument:
    expression: Expr
    bare_number: str | None
    literal_price: bool = False


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
    unit: UnitRule | None = None


@dataclass(frozen=True)
class KernelContext:
    columns: Mapping[str, Any]
    invalid_counts: MutableMapping[str, int]
    times: Any = None
    timeframe_seconds: int | None = None
    profile: ProfileWindow | None = None


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
    requires_clock: bool = False
    requires_profile: bool = False

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
            if role == "number" and arg.bare_number is None:
                raise InvalidCall(
                    "E203_TYPE", "Expected an unsuffixed numeric literal", index
                )
            if role == "price_literal" and not (arg.literal_price and expr.value > 0):
                raise InvalidCall(
                    "E203_TYPE", "Expected a positive price literal", index
                )
            normalized.append(expr)
        if self.validate is not None:
            self.validate(normalized)
        return tuple(normalized)

    def output_type(self, arguments: Sequence[Expr]) -> Type:
        def resolve(rule: UnitRule):
            return arguments[0].type.unit if rule == "source" else UNITS[rule]

        return Type(
            "record" if self.fields else "numeric",
            True,
            resolve(self.unit),
            tuple(field.name for field in self.fields),
            tuple(
                (field.name, resolve(field.unit))
                for field in self.fields
                if field.unit is not None
            ),
        )

    def field_ready(self, name: str, arguments: Sequence[Expr]) -> int:
        field = next(field for field in self.fields if field.name == name)
        return (field.readiness or self.readiness)(arguments)
