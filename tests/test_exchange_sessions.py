"""Scheduled candles, causal split factors, and exchange execution timestamps."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tradelang.api.contracts import AST_VALIDATOR_V7
from tradelang.compiler import compile_source
from tradelang.data import instant, load_dataset, prepare_window
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem
from tradelang.persistence import Library
from tradelang.report import explain, publish

FIXTURE = Path("docs/fixtures/exchange/session.csv")
SOURCE = FIXTURE.with_suffix(".trade").read_text()


def metadata():
    return json.loads(FIXTURE.with_suffix(".json").read_text())


def write(path, body):
    path.write_text("timestamp,open,high,low,close,volume\n" + body)
    return path


def test_holiday_open_short_session_and_split_reconcile_with_bundle(tmp_path):
    strategy = compile_source(SOURCE)
    AST_VALIDATOR_V7.validate(strategy.public())
    data = load_dataset(FIXTURE, metadata())
    result = execute(strategy, data)
    assert data.missing == 0
    assert [row["equity"] for row in result["equity"]][:4] == [1000, 1000, 1000, 1100]
    assert data.column("close").tolist() == [100, 100, 110, 120]
    assert data.column("volume").tolist() == [100, 100, 100, 100]
    assert data.split_factors.tolist() == [1, 1, 2, 2]
    assert data.raw_values[:, 3].tolist() == [100, 100, 55, 60]
    buys, sells = (event for event in result["events"] if event["kind"] == "fill")
    assert (buys["observed_at"], buys["fill_price"], buys["quantity"]) == (
        "2024-11-29T14:30:00Z",
        100,
        10,
    )
    assert (sells["observed_at"], sells["fill_price"], sells["split_factor"]) == (
        "2024-12-03T14:30:00Z",
        120,
        2,
    )
    assert result["summary"]["final_cash"] == 1200
    assert result["equity"][2]["timestamp"] == "2024-11-29T18:00:00Z"
    assert (
        explain(strategy, data)["resolved_window"]["first_signal_at"]
        == "2024-11-27T21:00:00Z"
    )
    assert any(
        w["details"].get("reason") == "session_intervals"
        for w in result["summary"]["warnings"]
    )

    bundle = tmp_path / "bundle"
    original = publish(strategy, data, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["decision_inspection"]["schema_version"] == 3
    assert manifest["resolved_policy"]["session_calendar"]["market"] == "XNYS"
    assert pq.read_table(bundle / "decisions.parquet")["split_factor"].to_pylist() == [
        1,
        1,
        2,
        2,
    ]
    copy = load_dataset(bundle / "input.csv", manifest["dataset_metadata"])
    replay = publish(strategy, copy, tmp_path / "replay")
    assert replay["run_fingerprint"] == original["run_fingerprint"]
    assert replay["result_digest"] == original["result_digest"]


def test_splits_apply_once_when_loading_a_library_import(tmp_path):
    library = Library(tmp_path / "library")
    now = datetime(2025, 1, 1, tzinfo=UTC)
    staged_source = tmp_path / "session.csv"
    staged_source.write_bytes(FIXTURE.read_bytes())
    row, _ = library.import_dataset(staged_source, "session.csv", metadata(), now)
    dataset = library.resolve_dataset(row["id"])
    assert dataset.raw_values[:, 3].tolist() == [100, 100, 55, 60]
    assert dataset.column("close").tolist() == [100, 100, 110, 120]
    assert dataset.dataset_hash == load_dataset(FIXTURE, metadata()).dataset_hash
    library.db.dispose()


def test_future_split_preserves_earlier_values_and_expiry_uses_real_close():
    meta = metadata()
    data = load_dataset(FIXTURE, meta)
    meta["splits"].append({"date": "2024-12-03", "new_shares": 3, "old_shares": 1})
    changed = load_dataset(FIXTURE, meta)
    assert changed.dataset_hash != data.dataset_hash
    assert changed.column("close").tolist() == [100, 100, 110, 360]
    result = execute(
        compile_source(
            SOURCE.replace("next bar open", "next bar open expire after 1d")
        ),
        data,
    )
    expired = next(
        event for event in result["events"] if event["kind"] == "order_expired_stale"
    )
    assert expired["observed_at"] == "2024-11-29T14:30:00Z"
    assert expired["age_seconds"] == 41.5 * 3600


def test_dst_uses_next_session_open_and_holiday_counts_only_scheduled_gaps(tmp_path):
    meta = metadata()
    meta["splits"] = []
    meta["session_schedule"].update(
        from_date="2024-03-08",
        to_date="2024-03-11",
        sessions=[
            {
                "date": "2024-03-08",
                "open": "2024-03-08T14:30:00Z",
                "close": "2024-03-08T21:00:00Z",
            },
            {
                "date": "2024-03-11",
                "open": "2024-03-11T13:30:00Z",
                "close": "2024-03-11T20:00:00Z",
            },
        ],
    )
    csv = write(
        tmp_path / "dst.csv",
        "2024-03-08T14:30:00Z,100,100,100,100,1\n2024-03-11T13:30:00Z,105,105,105,105,1\n",
    )
    data = load_dataset(csv, meta)
    result = execute(
        compile_source(
            SOURCE.replace("2024-11-27 to 2024-12-03", "2024-03-08 to 2024-03-11")
        ),
        data,
    )
    (fill,) = [event for event in result["events"] if event["kind"] == "fill"]
    assert fill["observed_at"] == "2024-03-11T13:30:00Z"
    assert data.missing == 0

    skipped = tmp_path / "missing.csv"
    skipped.write_text(
        "\n".join(
            line
            for line in FIXTURE.read_text().splitlines()
            if "2024-11-29" not in line
        )
        + "\n"
    )
    with pytest.raises(Problem, match="missing candle"):
        load_dataset(skipped, metadata())
    assert load_dataset(skipped, {**metadata(), "gap_policy": "allow"}).missing == 1


def test_session_higher_feed_and_profile_use_actual_shortened_closes(tmp_path):
    meta = metadata()
    meta.update(timeframe="2h", price_basis="raw_equity")
    meta.pop("splits")
    meta["session_schedule"].update(
        from_date="2024-11-29",
        to_date="2024-12-02",
        sessions=meta["session_schedule"]["sessions"][1:3],
    )
    rows = [
        ("2024-11-29T14:30:00Z", 100),
        ("2024-11-29T16:30:00Z", 105),
        ("2024-12-02T14:30:00Z", 110),
        ("2024-12-02T16:30:00Z", 110),
        ("2024-12-02T18:30:00Z", 110),
        ("2024-12-02T20:30:00Z", 110),
    ]
    primary = load_dataset(
        write(
            tmp_path / "primary.csv",
            "".join(f"{at},{p},{p},{p},{p},1\n" for at, p in rows),
        ),
        meta,
    )
    assert instant(primary.close_at(1)) == "2024-11-29T18:00:00Z"
    assert instant(primary.close_at(-1)) == "2024-12-02T21:00:00Z"
    daily = load_dataset(
        write(
            tmp_path / "daily.csv",
            "2024-11-29T14:30:00Z,105,105,105,105,1\n2024-12-02T14:30:00Z,110,110,110,110,1\n",
        ),
        {**meta, "timeframe": "1d"},
    )
    source = SOURCE.replace("2024-11-27 to 2024-12-03", "2024-11-29 to 2024-12-02")
    signal = compile_source(
        source.replace(
            "timeframe 1d", "timeframe 2h\nfeed daily timeframe 1d max_age 7d"
        ).replace(
            "when close == 100 price", "when align(on(daily, close)) >= 105 price"
        )
    )
    prepared = prepare_window(signal, primary, feeds={"daily": daily})
    assert prepared.feeds["daily"].indices.tolist() == [-1, 0, 0, 0, 0, 1]
    assert prepared.feeds["daily"].reason(2) is None
    profile = compile_source(
        source.replace(
            "when close == 100 price", "when VPROFILE(1, 1 price, 0.7).poc > 0 price"
        )
    )
    prepared = prepare_window(profile, daily, profile=primary)
    assert next(iter(prepared.profiles.values())).coverage.tolist() == [True, True]
    vwap = compile_source(
        source.replace("timeframe 1d", "timeframe 2h").replace(
            "when close == 100 price", "when VWAP() > 0 price"
        )
    )
    values = Evaluator(vwap, primary, len(rows) - 1).evaluate(next(vwap.calls("VWAP")))
    assert values.tolist() == [100, 102.5, 110, 110, 110, 110]
