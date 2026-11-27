"""Source inspection shared by the local CLI and HTTP transports."""

from .compiler import Compiler, is_portfolio_source
from .data import digest, prepare_window
from .model import Problem
from .portfolio import compile_portfolio, prepare_portfolio
from .portfolio_report import portfolio_inspection
from .report import explain, identity, resolved
from .run_config import configuration_view, configured_strategy


def inspect_source(
    source: bytes,
    command: str,
    dataset=None,
    *,
    profile=None,
    parameters=None,
    settings=None,
    origins=None,
    feeds=None,
    portfolio_assets=None,
):
    """Inspect exact source bytes. Domain failures retain their diagnostic spans."""
    if command not in ("validate", "explain"):
        raise ValueError("Unknown inspection command")
    response = dict(
        schema_version=1,
        valid=False,
        source_hash=digest(source),
        spec_hash=None,
        warmup_index=None,
        resolved_window=None,
        workload=None,
        diagnostics=[],
    )
    if command == "validate":
        response.update(spec=None, data_compatible=None)
    else:
        response.update(text=None, assumptions={})
    try:
        if is_portfolio_source(source):
            spec = compile_portfolio(source)
            if (
                dataset is not None
                or profile is not None
                or parameters
                or settings
                or feeds
            ):
                raise Problem(
                    "E305_PORTFOLIO", "Bind datasets and settings by asset alias"
                )
            prepared_portfolio = (
                prepare_portfolio(spec, portfolio_assets)
                if portfolio_assets is not None
                else None
            )
            inspection = portfolio_inspection(spec, prepared_portfolio)
            keys = (
                ("spec", "data_compatible")
                if command == "validate"
                else ("text", "assumptions")
            )
            response.update(
                {
                    key: inspection[key]
                    for key in (
                        *keys,
                        "source_hash",
                        "spec_hash",
                        "workload",
                        "warmup_index",
                        "resolved_window",
                    )
                },
                valid=True,
            )
            return response
        if portfolio_assets is not None:
            raise Problem("E305_PORTFOLIO", "Asset bindings require a DSL 9 portfolio")
        strategy = configured_strategy(
            source, settings, parameters=parameters, origins=origins, dataset=dataset
        )
        response.update(
            **identity(strategy),
            warmup_index=strategy.warmup,
            diagnostics=list(strategy.warnings),
        )
        if (dataset is not None or profile is not None) and command == "validate":
            response["data_compatible"] = False
        if profile is not None and dataset is None:
            raise Problem("E402_WINDOW", "A profile dataset requires a primary dataset")
        if feeds and dataset is None:
            raise Problem("E402_WINDOW", "A secondary feed requires a primary dataset")
        prepared = (
            prepare_window(strategy, dataset, profile, feeds=feeds)
            if dataset is not None
            else None
        )
        if prepared is not None:
            response["workload"] = prepared.workload
        if command == "explain":
            response.update(
                explain(
                    strategy, dataset, profile=profile, prepared=prepared, feeds=feeds
                )
            )
        else:
            if prepared is not None:
                response["resolved_window"] = resolved(
                    strategy, dataset, prepared=prepared
                )
                response["data_compatible"] = True
            response["spec"] = strategy.public()
        response["valid"] = True
        if strategy.run_settings is not None:
            response["run_configuration"] = configuration_view(
                strategy, dataset, profile
            )
    except Problem as error:
        response["diagnostics"].append(error.diagnostic)
    return response


def check_draft(source: bytes):
    """Collect editor diagnostics without returning a spec for invalid source."""
    result = inspect_source(source, "validate")
    records = []
    if result["spec"] is not None:
        records = [
            record_hint(
                binding["name"], binding["span"], binding["expression"]["inferred_type"]
            )
            for binding in result["spec"].get("bindings", [])
            if binding["expression"]["inferred_type"]["kind"] == "record"
        ]
    if (
        not result["valid"]
        and result["diagnostics"][0]["span"] is not None
        and not is_portfolio_source(source)
    ):
        try:
            compiler = Compiler(source)
            result["diagnostics"] = compiler.editor_errors(result["diagnostics"][0])
            records = [
                record_hint(
                    name, expression.span.model_dump(), expression.type.public()
                )
                for name, expression in compiler.names.items()
                if expression.type.kind == "record"
            ]
        except (RecursionError, OverflowError):
            pass  # Retain the exact-source error if recovery reaches a compiler limit.
    result["records"] = records
    result["diagnostics"] = [draft_fix(source, item) for item in result["diagnostics"]]
    return result


def record_hint(name, span, inferred):
    return dict(
        name=name,
        span=span,
        fields={field: info.get("scale") for field, info in inferred["fields"].items()},
    )


def draft_fix(source, item):
    span, suggestion = item["span"], item["suggestion"]
    if span is None or not suggestion:
        return item
    original = source[span["start_byte"] : span["end_byte"]].decode()
    replacement = None
    if (
        item["code"] == "E101_SYNTAX"
        and suggestion.startswith("Use ")
        and suggestion.endswith("(...)")
    ):
        replacement = suggestion[4:-5]
    elif (
        item["code"] == "E101_SYNTAX"
        and suggestion.startswith("Check the spelling. Did you mean ")
        and suggestion.endswith("(...)?")
        and " or " not in suggestion
    ):
        replacement = suggestion.removeprefix(
            "Check the spelling. Did you mean "
        ).removesuffix("(...)?")
    elif item["code"] == "E102_UNKNOWN_NAME" and original.isidentifier():
        replacement = suggestion
    elif (
        item["code"] == "E204_SELECTOR"
        and original.startswith(".")
        and original[1:].isidentifier()
        and suggestion.startswith("Use .")
    ):
        replacement = suggestion.removeprefix("Use ")
    elif item["code"] == "W_POINT_SCALE" and original.endswith("%"):
        literal = original[:-1].strip()
        if literal and all(char in "0123456789.eE+-" for char in literal):
            replacement = literal
    if replacement is None:
        return item
    return {
        **item,
        "details": {
            **item["details"],
            "replacement": replacement,
            "original": original,
        },
    }
