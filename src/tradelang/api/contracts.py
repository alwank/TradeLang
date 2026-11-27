"""Wire records for the local editor API."""

import json
from importlib.resources import files
from typing import Annotated, Literal
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..model import Scale, Span
from ..run_config import Gap, Origin, ParameterOverrides, RunSettings
from ..workload import Workload

Scalar = str | float | int | bool | None
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
UuidText = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        json_schema_extra={"format": "uuid"},
    ),
]
FeedSelections = Annotated[dict[str, UuidText], Field(max_length=1)]
AssetAlias = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DraftRequest(Closed):
    source: str = Field(
        description="Exact strategy source, at most 65,536 UTF-8 bytes."
    )


class PortfolioAssetSelection(Closed):
    strategy_id: UuidText
    strategy_revision: Annotated[int, Field(ge=1)]
    dataset_id: UuidText
    profile_dataset_id: UuidText | None = None
    feed_ids: FeedSelections = Field(default_factory=dict)
    settings: RunSettings | None = None

    @field_validator("strategy_id", "dataset_id", "profile_dataset_id")
    @classmethod
    def normalize_id(cls, value):
        return str(UUID(value)) if value is not None else None

    @field_validator("feed_ids")
    @classmethod
    def normalize_feeds(cls, value):
        return {name: str(UUID(ident)) for name, ident in value.items()}


class RunSelection(Closed):
    dataset_id: UuidText | None = None
    profile_dataset_id: UuidText | None = None
    feed_ids: FeedSelections = Field(default_factory=dict)
    parameters: ParameterOverrides = Field(default_factory=dict)
    preset_id: UuidText | None = None
    preset_revision: Annotated[int, Field(ge=1)] | None = None
    settings: RunSettings | None = None
    portfolio_assets: (
        Annotated[
            dict[AssetAlias, PortfolioAssetSelection], Field(min_length=2, max_length=8)
        ]
        | None
    ) = None


class SourceRequest(DraftRequest, RunSelection):
    pass


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


class RunConfiguration(Closed):
    schema_version: Literal[1]
    from_date: str
    to_date: str
    capital: float
    currency: str
    fee_rate: float
    slippage_rate: float
    dataset_hash: Hash | None
    profile_dataset_hash: Hash | None
    gap_policy: Gap | None
    parameters: ParameterOverrides
    origins: dict[str, Origin]


class Inspection(Closed):
    schema_version: Literal[1]
    valid: bool
    source_hash: Hash
    spec_hash: Hash | None
    warmup_index: int | None
    resolved_window: ResolvedWindow | None
    workload: Workload | None
    diagnostics: list[Diagnostic]
    run_configuration: RunConfiguration | None = None


AST_SCHEMA = json.loads(files(__package__).joinpath("strategy.schema.json").read_text())
AST_SCHEMA_V2 = json.loads(
    files(__package__).joinpath("strategy-v2.schema.json").read_text()
)
AST_SCHEMA_V3 = json.loads(
    files(__package__).joinpath("strategy-v3.schema.json").read_text()
)
AST_SCHEMA_V4 = json.loads(
    files(__package__).joinpath("strategy-v4.schema.json").read_text()
)
AST_SCHEMA_V5 = json.loads(
    files(__package__).joinpath("strategy-v5.schema.json").read_text()
)
AST_SCHEMA_V6 = json.loads(
    files(__package__).joinpath("strategy-v6.schema.json").read_text()
)
AST_SCHEMA_V7 = json.loads(
    files(__package__).joinpath("strategy-v7.schema.json").read_text()
)
AST_SCHEMA_V8 = json.loads(
    files(__package__).joinpath("strategy-v8.schema.json").read_text()
)
AST_SCHEMA_V9 = json.loads(
    files(__package__).joinpath("strategy-v9.schema.json").read_text()
)
AST_VALIDATOR = Draft202012Validator(AST_SCHEMA)
AST_VALIDATOR_V2 = Draft202012Validator(AST_SCHEMA_V2)
AST_VALIDATOR_V3 = Draft202012Validator(AST_SCHEMA_V3)
AST_VALIDATOR_V4 = Draft202012Validator(AST_SCHEMA_V4)
AST_VALIDATOR_V5 = Draft202012Validator(AST_SCHEMA_V5)
AST_VALIDATOR_V6 = Draft202012Validator(AST_SCHEMA_V6)
AST_VALIDATOR_V7 = Draft202012Validator(AST_SCHEMA_V7)
AST_VALIDATOR_V8 = Draft202012Validator(AST_SCHEMA_V8)
AST_VALIDATOR_V9 = Draft202012Validator(AST_SCHEMA_V9)


class CompilationResponse(Inspection):
    spec: dict | None
    data_compatible: bool | None

    @field_validator("spec")
    @classmethod
    def validate_spec(cls, spec):
        if spec is not None:
            validators = {
                1: AST_VALIDATOR,
                2: AST_VALIDATOR_V2,
                3: AST_VALIDATOR_V3,
                4: AST_VALIDATOR_V4,
                5: AST_VALIDATOR_V5,
                6: AST_VALIDATOR_V6,
                7: AST_VALIDATOR_V7,
                8: AST_VALIDATOR_V8,
                9: AST_VALIDATOR_V9,
            }
            validators.get(spec.get("schema_version"), AST_VALIDATOR).validate(spec)
        return spec


class DraftRecord(Closed):
    name: str
    span: Span
    fields: dict[str, Scale | None]


class DraftCheckResponse(CompilationResponse):
    records: list[DraftRecord]


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
