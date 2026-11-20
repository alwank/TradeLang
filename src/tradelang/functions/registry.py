"""Static, read-only lookup for the packaged language vocabulary."""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .builtins import BUILTINS
from .contracts import Function


def build_registry(functions: Iterable[Function]) -> Mapping[str, Function]:
    catalog = {}
    for function in functions:
        if function.name in catalog:
            raise ValueError(f"Duplicate function {function.name}")
        if not callable(function.kernel) or not callable(function.readiness):
            raise ValueError(f"Missing kernel or readiness for {function.name}")
        if function.unit not in ("source", "price", "ratio"):
            raise ValueError(f"Invalid output unit for {function.name}")
        signatures = function.signatures
        arities = {len(signature.roles) for signature in signatures}
        canonical_roles = {signature.canonical_roles for signature in signatures}
        if (
            not signatures
            or len(arities) != len(signatures)
            or len(canonical_roles) != 1
        ):
            raise ValueError(f"Inconsistent signatures for {function.name}")
        (roles,) = canonical_roles
        if (
            any(role not in ("source", "period", "multiplier") for role in roles)
            or roles.count("source") > 1
            or ("source" in roles and roles[0] != "source")
            or (function.unit == "source" and "source" not in roles)
            or "period" not in roles
        ):
            raise ValueError(f"Invalid parameter roles for {function.name}")
        names = [field.name for field in function.fields]
        if len(names) != len(set(names)) or any(
            not field.name
            or (field.readiness is not None and not callable(field.readiness))
            for field in function.fields
        ):
            raise ValueError(f"Invalid record fields for {function.name}")
        catalog[function.name] = function
    return MappingProxyType(dict(sorted(catalog.items())))


FUNCTIONS = build_registry(BUILTINS)
