"""Wire records for the local editor API."""

import json
from importlib.resources import files
from typing import Annotated, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..model import Span

Scalar = str | float | int | bool | None
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
UuidText = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        json_schema_extra={"format": "uuid"},
    ),
]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SourceRequest(Closed):
    source: str = Field(
        description="Exact strategy source, at most 65,536 UTF-8 bytes."
    )
    dataset_id: UuidText | None = None


class Diagnostic(Closed):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    span: Span | None
    node_id: str | None
    suggestion: str | None
    data_row: int | None
    details: dict[str, Scalar]


class ResolvedWindow(Closed):
    first_open: str
    last_close_at: str
    readiness_index: int
    first_signal_at: str
    first_execution_at: str


class Inspection(Closed):
    schema_version: Literal[1]
    valid: bool
    source_hash: Hash
    spec_hash: Hash | None
    warmup_index: int | None
    resolved_window: ResolvedWindow | None
    diagnostics: list[Diagnostic]


AST_SCHEMA = json.loads(files(__package__).joinpath("strategy.schema.json").read_text())
AST_VALIDATOR = Draft202012Validator(AST_SCHEMA)


class CompilationResponse(Inspection):
    spec: dict | None
    data_compatible: bool | None

    @field_validator("spec")
    @classmethod
    def validate_spec(cls, spec):
        if spec is not None:
            AST_VALIDATOR.validate(spec)
        return spec


class ExplainResponse(Inspection):
    text: str | None
    assumptions: dict[str, Scalar]


class Error(Closed):
    code: str
    message: str
    diagnostics: list[Diagnostic]
    retryable: bool


class ErrorEnvelope(Closed):
    schema_version: Literal[1]
    request_id: UuidText
    error: Error


class Health(Closed):
    schema_version: Literal[1]
    status: Literal["ok", "degraded"]
    worker_available: bool
    queue_depth: Annotated[int, Field(ge=0)]
