"""Candle pairing, profile arithmetic, and two-input replay."""

import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from language_cases import CLOCK, METADATA, expression_text, strategy_text

from tradelang.api import create_app
from tradelang.application import inspect_source
from tradelang.compiler import compile_source
from tradelang.data import digest, hash_json, load_dataset, prepare_window
from tradelang.evaluator import Evaluator
from tradelang.functions import profile
from tradelang.functions.contracts import KernelContext
from tradelang.model import Problem
from tradelang.report import publish


def candle_file(
    path, hours, prices, weights, *, timeframe, gap_policy="reject", **kwargs
):
    rows = ["timestamp,open,high,low,close,volume"]
    rows.extend(
        f"2024-01-01T{hour:02}:00:00Z,{price},{price},{price},{price},{volume}"
        for hour, price, volume in zip(hours, prices, weights, strict=True)
    )
    path.write_text("\n".join(rows) + "\n")
    return load_dataset(
        path,
        {**METADATA, "timeframe": timeframe, "gap_policy": gap_policy, **kwargs},
        as_of_utc=CLOCK,
    )


@pytest.fixture
def paired(tmp_path):
    primary = candle_file(
        tmp_path / "primary.csv", [0, 8, 16], [102, 110, 109], [9, 3, 4], timeframe="8h"
    )
    child = candle_file(
        tmp_path / "child.csv",
        [0, 4, 8, 12, 16, 20],
        [100.2, 101.2, 100.9, 102.2, 104.2, 106.2],
        [3, 6, 0, 3, 2, 2],
        timeframe="4h",
    )
    source = strategy_text(
        lets="let point = VPROFILE(2, 1 price, 0.7).poc",
        entry="close > point",
        end="2024-01-01",
    ).replace("1d", "8h")
    return compile_source(source), primary, child


def kernel_profiles(primary, child, prices, volumes, key, *, parent_width=2):
    windows = profile.prepare_profiles(
        np.asarray(primary),
        parent_width,
        np.asarray(child),
        1,
        np.asarray(prices),
        np.asarray(volumes),
        [key],
    )
    return profile.vprofile(key, KernelContext({}, {}, profile=windows[key]))


def test_alignment_including_interval_close_and_area_tie():
    out = kernel_profiles(
        [0, 2, 4],
        range(6),
        [100, 101, 101, 102, 104, 106],
        [3, 6, 0, 3, 2, 2],
        (2, 1, 0.7),
    )
    np.testing.assert_equal(out["poc"], [np.nan, 101.5, 102.5])
    np.testing.assert_equal(out["val"], [np.nan, 100, 102])
    np.testing.assert_equal(out["vah"], [np.nan, 102, 105])


@given(seed=st.integers(min_value=0, max_value=65_535), period=st.integers(2, 12))
def test_running_profile_matches_independent_window_histograms_and_prefixes(
    seed, period
):
    rng = np.random.default_rng(seed)
    parent = np.arange(24) * 2
    stamps = np.arange(len(parent) * 2)
    prices = rng.integers(92, 112, size=len(stamps))
    volumes = rng.integers(0, 6, size=len(stamps))
    volumes[::2] += 1
    fraction = Fraction(0.7)
    rows = kernel_profiles(parent, stamps, prices, volumes, (period, 1, 0.7))
    earlier = kernel_profiles(parent[:21], stamps, prices, volumes, (period, 1, 0.7))
    for name in earlier:
        np.testing.assert_equal(earlier[name], rows[name][:21])
    for row in range(period - 1, len(parent)):
        hist = Counter()
        window = range((row - period + 1) * 2, (row + 1) * 2)
        for child in window:
            if volumes[child] > 0:
                hist[int(prices[child])] += int(volumes[child])
        start = min(hist, key=lambda key: (-hist[key], key))
        selected = [start]
        target = fraction * sum(hist.values())
        while sum(hist[key] for key in selected) < target:
            boundary = set(range(min(hist), max(hist) + 1)) & {
                min(selected) - 1,
                max(selected) + 1,
            }
            selected.append(min(boundary, key=lambda key: (-hist[key], key)))
        assert rows["poc"][row] == start + 0.5
        assert rows["val"][row] == min(selected)
        assert rows["vah"][row] == max(selected) + 1


def test_missing_child_and_missing_parent_are_distinct():
    observed = [0, 2, 6, 8]
    child = list(range(10))
    prices = [100, 101, 100, 101, 750, 760, 99, 98, 100, 101]
    volume = [1] * len(prices)
    complete = kernel_profiles(observed, child, prices, volume, (2, 1, 1))
    np.testing.assert_equal(complete["vah"], [np.nan, 102, 102, 102])
    dropped = kernel_profiles(
        observed,
        child[:2] + child[3:],
        prices[:2] + prices[3:],
        volume[:2] + volume[3:],
        (2, 1, 1),
    )
    np.testing.assert_equal(dropped["poc"], [np.nan, np.nan, np.nan, 98.5])


def test_zero_volume_span_limit_and_recovery():
    out = kernel_profiles(
        [0, 2, 4, 6],
        range(8),
        [100, 101, 100, 1000, 100, 101, 100, 101],
        [0, 0, 1, 1, 1, 3, 2, 1],
        (1, 1, 1),
    )
    np.testing.assert_equal(out["poc"], [np.nan, np.nan, 101.5, 100.5])
    np.testing.assert_equal(out["val"], [np.nan, np.nan, 100, 100])
    np.testing.assert_equal(out["vah"], [np.nan, np.nan, 102, 102])


def test_work_admission_at_and_beyond_limit(monkeypatch):
    args = ([0, 2], [0, 1, 2, 3], [100, 101, 100, 101], [1, 1, 1, 1], (1, 1, 1))
    monkeypatch.setattr(profile, "MAX_PROFILE_WORK", 16)
    assert all(np.isfinite(kernel_profiles(*args)["poc"]))
    monkeypatch.setattr(profile, "MAX_PROFILE_WORK", 15)
    with pytest.raises(Problem) as error:
        kernel_profiles(*args)
    assert error.value.diagnostic["code"] == "E_DATA_LIMIT"


def test_call_arguments_and_normalized_limit():
    compile_source(expression_text("VPROFILE(256, 1 price, 1).poc"))
    for expression, code in (
        ("VPROFILE(257, 1 price, 0.7).poc", "E202_PERIOD"),
        ("VPROFILE(2, 1, 0.7).poc", "E203_TYPE"),
        ("VPROFILE(2, (1 price), 0.7).poc", "E203_TYPE"),
        ("VPROFILE(2, 1 price, 70%).poc", "E203_TYPE"),
        ("VPROFILE(2, 0 price, 0.7).poc", "E203_TYPE"),
    ):
        with pytest.raises(Problem) as exc:
            compile_source(expression_text(expression))
        assert exc.value.diagnostic["code"] == code
    many = "\n".join(f"let x{n} = VPROFILE({n}, 1 price, 0.7).poc" for n in range(1, 6))
    with pytest.raises(Problem, match="four distinct"):
        compile_source(strategy_text(lets=many))
    compile_source(strategy_text(lets=many.replace("VPROFILE(5, 1", "VPROFILE(1, 1.0")))


def test_inspector_cli_and_http_transport(paired, tmp_path):
    strategy, primary, child = paired
    assert inspect_source(strategy.source, "validate")["valid"]
    missing = inspect_source(strategy.source, "validate", primary)
    assert not missing["valid"]
    assert missing["diagnostics"][0]["code"] == "E402_WINDOW"
    assert not inspect_source(strategy.source, "validate", profile=child)["valid"]
    assert not inspect_source(strategy.source, "validate", primary, profile=primary)[
        "valid"
    ]
    assert not inspect_source(
        expression_text("SMA(1)").encode(), "validate", primary, profile=child
    )["valid"]

    from typer.testing import CliRunner

    from tradelang.cli import app

    text_path = tmp_path / "paired.trade"
    text_path.write_bytes(strategy.source)
    primary_meta, child_meta = tmp_path / "primary.json", tmp_path / "child.json"
    primary_meta.write_text(primary.meta.model_dump_json())
    child_meta.write_text(child.meta.model_dump_json())
    flags = [
        str(text_path),
        "--data",
        str(primary.path),
        "--metadata",
        str(primary_meta),
        "--profile-data",
        str(child.path),
        "--profile-metadata",
        str(child_meta),
        "--json",
    ]
    runner = CliRunner()
    for command in ("validate", "explain"):
        response = runner.invoke(app, [command, *flags])
        assert response.exit_code == 0, response.output
        assert json.loads(response.output)["ok"]
    bundle = tmp_path / "cli-bundle"
    run = runner.invoke(app, ["backtest", *flags, "--out", str(bundle)])
    assert run.exit_code == 0, run.output
    assert (bundle / "profile-input.csv").is_file()

    primary_id, child_id = uuid4(), uuid4()
    api = create_app({primary_id: primary, child_id: child}.get)
    headers = {"Origin": "http://127.0.0.1:3000"}
    payload = {"source": strategy.source.decode(), "dataset_id": str(primary_id)}
    with TestClient(
        api, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    ) as client:
        for command in ("validate", "explain"):
            endpoint = f"/api/v1/strategies/{command}"
            response = client.post(endpoint, headers=headers, json=payload)
            assert response.status_code == 200
            assert response.json()["diagnostics"][-1]["code"] == "E402_WINDOW"
            response = client.post(
                endpoint,
                headers=headers,
                json={**payload, "profile_dataset_id": str(child_id)},
            )
            assert response.status_code == 200
            assert response.json()["valid"]
        response = client.post(
            "/api/v1/strategies/validate",
            headers=headers,
            json={**payload, "profile_dataset_id": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "E_DATASET_NOT_FOUND"


def test_published_profile_replays_and_tracks_child_changes(paired, tmp_path):
    strategy, primary, child = paired
    target = tmp_path / "bundle"
    run = publish(strategy, primary, target, profile=child)
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["schema_version"] == 3
    assert manifest["profile_dataset"] == {
        "role": "volume_profile",
        "dataset_hash": child.dataset_hash,
    }
    signature_keys = (
        "dsl_version",
        "semantics_version",
        "spec_hash",
        "dataset_hash",
        "environment_hash",
        "config_hash",
        "profile_dataset",
    )
    assert (
        hash_json({key: manifest[key] for key in signature_keys})
        == run["run_fingerprint"]
    )
    for file in manifest["artifact_files"]:
        assert digest((target / file["name"]).read_bytes()) == file["sha256"]
    copy = load_dataset(
        target / manifest["profile_input"]["data_file"],
        json.loads((target / manifest["profile_input"]["metadata_file"]).read_text()),
        as_of_utc=CLOCK,
    )
    replay = publish(strategy, primary, tmp_path / "replay", profile=copy)
    assert replay["result_digest"] == run["result_digest"]
    assert replay["run_fingerprint"] == run["run_fingerprint"]
    alternative = candle_file(
        tmp_path / "other.csv",
        [0, 4, 8, 12, 16, 20],
        [100.2, 101.2, 100.9, 102.2, 104.2, 106.2],
        [3, 6, 0, 30, 2, 2],
        timeframe="4h",
    )
    assert alternative.dataset_hash != child.dataset_hash
    assert (
        publish(strategy, primary, tmp_path / "other", profile=alternative)[
            "run_fingerprint"
        ]
        != run["run_fingerprint"]
    )
    events = [
        json.loads(row) for row in (target / "events.jsonl").read_text().splitlines()
    ]
    assert any(
        event["kind"] == "fill" and event["observed_at"] == "2024-01-01T16:00:00Z"
        for event in events
    )


def test_child_csv_and_parquet_identity_and_partial_publication(paired, tmp_path):
    strategy, primary, child = paired
    path = tmp_path / "child.parquet"
    pq.write_table(
        pa.table(
            {
                "timestamp": pa.array(child.times, type=pa.timestamp("us", "UTC")),
                **{
                    name: child.column(name)
                    for name in ("open", "high", "low", "close", "volume")
                },
            }
        ),
        path,
    )
    encoded = load_dataset(path, child.meta.model_dump(), as_of_utc=CLOCK)
    assert child.dataset_hash == encoded.dataset_hash
    first = publish(strategy, primary, tmp_path / "csv", profile=child)
    second = publish(strategy, primary, tmp_path / "parquet", profile=encoded)
    assert first["run_fingerprint"] == second["run_fingerprint"]
    assert first["result_digest"] == second["result_digest"]
    child.path.write_text(child.path.read_text() + "\n")
    failed = tmp_path / "failed"
    with pytest.raises(Problem, match="changed after loading"):
        publish(strategy, primary, failed, profile=child)
    assert not failed.exists()
    assert list(Path(tmp_path).glob(".failed-*")) == []


def test_prepared_evaluator_reuses_normalized_profile(paired):
    strategy, primary, child = paired
    prepared = prepare_window(strategy, primary, child)
    ev = Evaluator(strategy, primary, prepared.last, profiles=prepared.profiles)
    result = ev.evaluate(strategy.bindings[0][1])
    np.testing.assert_equal(result, [np.nan, 101.5, 102.5])
    assert len(ev.call_cache) == 1
