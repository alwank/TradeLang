"""Preflight memory bounds and shared CLI and HTTP workload evidence."""

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from language_cases import CLOCK, METADATA, strategy_text
from typer.testing import CliRunner

from tradelang import workload
from tradelang.api import create_app
from tradelang.cli import app
from tradelang.compiler import compile_source
from tradelang.data import load_dataset, prepare_window
from tradelang.model import Problem
from tradelang.persistence import Library
from tradelang.report import publish

FIXTURES = Path("docs/fixtures")
ORIGIN = {"Origin": "http://127.0.0.1:3000"}


def test_workload_counts_shared_kernel_and_binding_backings():
    dataset = load_dataset(FIXTURES / "core.csv", METADATA, as_of_utc=CLOCK)
    common = "let avg = SMA(1)"
    simple = compile_source(strategy_text(lets=common, entry="close > avg"))
    shared = compile_source(
        strategy_text(
            lets=common + "\nlet alias = avg[0]\nlet reuse = SMA(close, 1)",
            entry="close > alias",
        )
    )
    first = prepare_window(simple, dataset).workload
    second = prepare_window(shared, dataset).workload
    assert first["kernel_calls"] == second["kernel_calls"] == 1
    assert first["retained_series_bytes"] == second["retained_series_bytes"]
    assert first["minimum_resident_bytes"] == second["minimum_resident_bytes"]
    assert first["evaluated_rows"] == first["execution_rows"] == 3
    assert first["retained_series"] == 3  # SMA output and two predicates.
    assert first["event_count_ceiling"] == 24


def test_prepare_rejects_provably_over_budget_arrays_with_default_limit():
    dataset = load_dataset(FIXTURES / "core.csv", METADATA, as_of_utc=CLOCK)
    days = 400
    row_count = days * 1440
    dataset = replace(
        dataset,
        meta=dataset.meta.model_copy(update={"timeframe": "1m"}),
        times=int(dataset.times[0]) + np.arange(row_count, dtype=np.int64) * 60_000_000,
        values=np.ones((row_count, 5)),
    )
    declarations = "\n".join(
        f"let value{i} = close * {i + 1} + 1 price" for i in range(128)
    )
    source = strategy_text(
        lets=declarations, end=(date(2024, 1, 1) + timedelta(days=days - 1)).isoformat()
    )
    with pytest.raises(Problem) as stopped:
        prepare_window(compile_source(source.replace("1d", "1m")), dataset)
    diagnostic = stopped.value.diagnostic
    assert diagnostic["code"] == "E_DATA_LIMIT"
    assert diagnostic["details"]["minimum_resident_bytes"] > 1024**3
    assert diagnostic["details"]["memory_limit_bytes"] == 1024**3
    assert diagnostic["details"]["dominant_expression"] == "let value0"


def test_preflight_matches_cli_http_snapshot_and_publication(tmp_path, monkeypatch):
    source = (FIXTURES / "core.trade").read_text()
    dataset = load_dataset(FIXTURES / "core.csv", METADATA, as_of_utc=CLOCK)
    expected = prepare_window(compile_source(source), dataset).workload
    cli = CliRunner()
    args = [
        str(FIXTURES / "core.trade"),
        "--data",
        str(FIXTURES / "core.csv"),
        "--metadata",
        str(FIXTURES / "metadata.json"),
    ]
    library = Library(tmp_path / "library")
    with TestClient(
        create_app(library=library, worker_available=lambda: True),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
    ) as client:
        imported = client.post(
            "/api/v1/datasets/import",
            headers=ORIGIN,
            files={
                "file": ("core.csv", dataset.path.read_bytes()),
                "metadata": (None, json.dumps(METADATA)),
            },
        )
        assert imported.status_code == 201, imported.text
        selected = imported.json()["dataset"]["id"]
        saved = client.post(
            "/api/v1/strategies",
            headers=ORIGIN,
            json={"name": "Budget", "source": source},
        )
        assert saved.status_code == 201, saved.text
        payload = {
            "strategy_id": saved.json()["id"],
            "strategy_revision": 1,
            "dataset_id": selected,
        }
        for command in ("validate", "explain"):
            http = client.post(
                f"/api/v1/strategies/{command}",
                headers=ORIGIN,
                json={"source": source, "dataset_id": selected},
            )
            wire = cli.invoke(app, [command, *args, "--json"])
            assert wire.exit_code == 0, wire.output
            assert (
                http.json()["workload"]
                == json.loads(wire.stdout)["result"]["workload"]
                == expected
            )
        assert "resident bytes" in cli.invoke(app, ["validate", *args]).stdout

        # Check both admission boundaries without allocating a gigabyte.
        monkeypatch.setattr(
            workload, "MEMORY_LIMIT_BYTES", expected["minimum_resident_bytes"] - 1
        )
        rejected = client.post("/api/v1/backtests", headers=ORIGIN, json=payload)
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "E_DATA_LIMIT"
        assert client.get("/api/v1/backtests").json()["items"] == []
        wire = cli.invoke(app, ["validate", *args, "--json"])
        assert wire.exit_code == 2
        assert json.loads(wire.stdout)["diagnostics"][0]["code"] == "E_DATA_LIMIT"

        monkeypatch.setattr(
            workload, "MEMORY_LIMIT_BYTES", expected["minimum_resident_bytes"]
        )
        accepted = client.post("/api/v1/backtests", headers=ORIGIN, json=payload)
        assert accepted.status_code == 202, accepted.text
        revised = {**expected, "memory_limit_bytes": expected["minimum_resident_bytes"]}
        assert accepted.json()["workload"] == revised
        output = tmp_path / "bundle"
        publish(compile_source(source), dataset, output)
        assert json.loads((output / "manifest.json").read_text())["workload"] == revised
