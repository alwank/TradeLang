"""Run inert, versioned compiler cases with full diagnostic and span assertions."""

from typing import Literal, Self

import pytest
from language_cases import BASELINE, FIXTURES, expression_text
from pydantic import BaseModel, ConfigDict, model_validator

from tradelang.application import inspect_source
from tradelang.compiler import compile_source

CLAUSES = Literal["V1-TYPE06", "V1-TYPE08", "V1-TYPE09", "V1-ERR01", "V1-READY01"]
ACCEPTANCE = Literal["P1-AC03", "P1-AC04", "P1-AC06", "P2-AC02", "P2-AC04"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Failure(Record):
    code: str
    message: str
    from_column: int
    to_column: int
    suggestion: str | None = None


class Case(Record):
    case_id: str
    clauses: list[CLAUSES]
    acceptance: list[ACCEPTANCE]
    expression: str
    derivation: str
    failure: Failure | None = None
    ready: int | None = None

    @model_validator(mode="after")
    def check_expectations(self) -> Self:
        if (self.failure is None) == (self.ready is None):
            raise ValueError(
                "Each case requires exactly one phase-specific expectation"
            )
        if not all((self.case_id, self.clauses, self.acceptance, self.derivation)):
            raise ValueError("Cases require identifiers, traceability and a derivation")
        return self


class Catalog(Record):
    baseline_sha: Literal[BASELINE]
    dsl_version: Literal[1]
    spec_schema_version: Literal[1]
    phase: Literal["compile"]
    cases: list[Case]

    @model_validator(mode="after")
    def check_case_ids(self) -> Self:
        if not self.cases or len({case.case_id for case in self.cases}) != len(
            self.cases
        ):
            raise ValueError("Case IDs must be unique")
        return self


CATALOG = Catalog.model_validate_json((FIXTURES / "compiler-cases.json").read_bytes())


@pytest.mark.parametrize("case", CATALOG.cases, ids=lambda case: case.case_id)
def test_compiler_fixture(case):
    raw = expression_text(case.expression).encode()
    observed = inspect_source(raw, "validate")
    if case.failure is None:
        assert observed["valid"] and observed["spec"] is not None
        assert observed["warmup_index"] == case.ready
        assert compile_source(raw).bindings[0][1].ready == case.ready
        return

    assert observed["valid"] is False
    assert observed["spec"] is None
    assert observed["spec_hash"] is None
    failure = case.failure
    line_start = raw.index(b"let value")
    line = raw[:line_start].count(b"\n") + 1
    assert observed["diagnostics"] == [
        {
            "code": failure.code,
            "severity": "error",
            "message": failure.message,
            "span": {
                "start_line": line,
                "end_line": line,
                "start_column": failure.from_column,
                "end_column": failure.to_column,
                "start_byte": line_start + failure.from_column - 1,
                "end_byte": line_start + failure.to_column - 1,
            },
            "suggestion": failure.suggestion,
            "node_id": None,
            "data_row": None,
            "details": {},
        }
    ]
