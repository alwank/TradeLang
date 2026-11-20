"""Exact compatibility with the pre-registry compiler and evaluator."""

import io
import json
import math
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import numpy as np
from language_cases import BASELINE, CLOCK, FIXTURES, METADATA

from tradelang.application import inspect_source
from tradelang.compiler import compile_source
from tradelang.data import canonical, load_dataset
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.report import projection, publish

ROOT = FIXTURES.parents[2]
IDENTITIES = (
    "source_hash",
    "spec_hash",
    "dataset_hash",
    "config_hash",
    "result_digest",
    "dsl_version",
    "semantics_version",
    "schema_version",
)


def finite_bits(series):
    # Hex retains every binary64 bit of a finite sample, including the sign of zero.
    return [float(v).hex() if math.isfinite(v) else None for v in series]


def catalog_snapshot(output):
    source = (FIXTURES / "catalog.trade").read_bytes()
    strategy = compile_source(source)
    dataset = load_dataset(
        FIXTURES / "indicators.csv",
        METADATA,
        as_of_utc=CLOCK,
    )
    values = {}
    counters = {}
    checks = {}
    for end in range(len(dataset.times)):
        evaluator = Evaluator(strategy, dataset, end)
        for name, node, _ in strategy.bindings:
            vector = evaluator.evaluate(node)
            if end == len(dataset.times) - 1:
                values[name] = {"ready": node.ready, "values": finite_bits(vector)}
                if node.op == "field":
                    call = node.args[0]
                    record = evaluator.evaluate(call)
                    values[name]["record"] = {
                        "ready": call.ready,
                        "order": list(record),
                        "values": {
                            key: finite_bits(value) for key, value in record.items()
                        },
                    }
            checks[end, name] = finite_bits(vector)
        counters[str(end)] = {
            "reasons": evaluator.invalid,
            "calls": len(evaluator.call_cache),
        }
    for (end, name), prefix in checks.items():
        assert prefix == values[name]["values"][: end + 1], (name, end)

    validated = inspect_source(source, "validate", dataset)
    public = validated["spec"]
    projected = projection(
        {key: value for key, value in public.items() if key != "name"}
    )
    publish(strategy, dataset, output)
    manifest = json.loads((output / "manifest.json").read_text())
    ledger = execute(strategy, dataset)
    ledger["equity"] = list(ledger["equity"])
    return {
        "validate": validated,
        "explain": inspect_source(source, "explain", dataset),
        "projected_bytes": canonical(projected),
        "vectors": values,
        "prefix_counters": counters,
        "identities": {key: manifest[key] for key in IDENTITIES},
        "raw_data_hash": dataset.source_hash,
        "ledger": ledger,
    }


def environment_identity(output):
    manifest = json.loads((output / "manifest.json").read_text())
    return {
        key: manifest[key]
        for key in ("code_revision", "environment_hash", "run_fingerprint")
    }


def test_catalog_baseline_parity(tmp_path):
    fixture_path = FIXTURES / "catalog-baseline.json"
    fixture = json.loads(fixture_path.read_text())
    assert fixture["provenance"]["baseline_sha"] == BASELINE
    # Isolate the pinned source in a subprocess with the same lock and interpreter.
    # A macOS capture is retained for review. On another platform the local baseline
    # supplies the exact bits, including platform-sensitive annualized metrics.
    archive = subprocess.check_output(
        ["git", "archive", BASELINE, "src/tradelang"], cwd=ROOT
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(tmp_path, filter="data")
    baseline_output = tmp_path / "baseline"
    result = subprocess.check_output(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--snapshot",
            str(baseline_output),
        ],
        env={**os.environ, "PYTHONPATH": str(tmp_path / "src")},
        text=True,
        timeout=30,
    )
    expected = json.loads(result)
    provenance = fixture["provenance"]
    if (
        platform.system() == provenance["system"]
        and platform.machine() == provenance["machine"]
        and platform.python_version() == provenance["python"]
        and np.__version__ == provenance["numpy"]
    ):
        assert expected == fixture["expected"]

    candidate_output = tmp_path / "candidate"
    assert catalog_snapshot(candidate_output) == expected
    before, after = (
        environment_identity(out) for out in (baseline_output, candidate_output)
    )
    assert all(before[key] != after[key] for key in before)


def capture_fixture():
    # Explicit maintenance command. Pytest never writes expected records.
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if revision != BASELINE:
        raise SystemExit(f"Capture requires the baseline revision {BASELINE}")
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "src",
            "uv.lock",
            "pyproject.toml",
        ],
        cwd=ROOT,
        check=True,
    )
    with tempfile.TemporaryDirectory() as directory:
        snapshot = catalog_snapshot(Path(directory) / "catalog")
    fixture = {
        "provenance": {
            "case_id": "I-CATALOG-01",
            "baseline_sha": BASELINE,
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "command": "uv run --locked --extra api python tests/test_registry_parity.py",
            "oracle_kind": "baseline snapshot",
            "as_of_utc": CLOCK.isoformat(),
            "derivation": "Compare the pre-registry implementation with the same source and candles. "
            "Independent mathematics and ledger assertions live in the indicator and execution suites.",
            "exclusions": [
                "environment_hash",
                "run_fingerprint",
                "run_id",
                "wall-clock timestamps",
            ],
        },
        "expected": snapshot,
    }
    (FIXTURES / "catalog-baseline.json").write_text(
        json.dumps(fixture, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--snapshot":
        print(json.dumps(catalog_snapshot(Path(sys.argv[2])), allow_nan=False))
    elif len(sys.argv) == 1:
        capture_fixture()
    else:
        raise SystemExit("Expected no arguments or --snapshot DIRECTORY")
