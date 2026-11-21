"""Source inspection shared by the local CLI and HTTP transports."""

from .compiler import compile_source
from .data import digest
from .model import Problem
from .report import explain, identity, resolved


def inspect_source(source: bytes, command: str, dataset=None, *, profile=None):
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
        diagnostics=[],
    )
    if command == "validate":
        response.update(spec=None, data_compatible=None)
    else:
        response.update(text=None, assumptions={})
    try:
        strategy = compile_source(source)
        response.update(
            **identity(strategy),
            warmup_index=strategy.warmup,
            diagnostics=list(strategy.warnings),
        )
        if (dataset is not None or profile is not None) and command == "validate":
            response["data_compatible"] = False
        if profile is not None and dataset is None:
            raise Problem("E402_WINDOW", "A profile dataset requires a primary dataset")
        if command == "explain":
            response.update(explain(strategy, dataset, profile=profile))
        else:
            if dataset is not None:
                response["resolved_window"] = resolved(
                    strategy, dataset, profile=profile
                )
                response["data_compatible"] = True
            response["spec"] = strategy.public()
        response["valid"] = True
    except Problem as error:
        response["diagnostics"].append(error.diagnostic)
    return response
