"""Import, preparation, evaluation, order proposal and fatal execution boundaries."""

import json
from datetime import UTC, datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from language_cases import CLOCK, FIXTURES, METADATA, expression_text, strategy_text

from tradelang.compiler import compile_source
from tradelang.data import load_dataset, window
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem
from tradelang.report import publish


@pytest.mark.parametrize(
    ("nanosecond_offset", "volume", "explanation"),
    [
        (0, 2**53, None),
        (0, 2**53 + 1, "Integer value"),
        (1, 1, "lose data"),
    ],
)
def test_parquet_safe_cast_boundaries(tmp_path, nanosecond_offset, volume, explanation):
    file = tmp_path / "candles.parquet"
    stamp = 1704067200 * 10**9 + nanosecond_offset  # 2024-01-01T00:00:00Z
    columns = dict(
        timestamp=pa.array([stamp], type=pa.timestamp("ns", tz="UTC")),
        open=[10],
        high=[11],
        low=[9],
        close=[10],
        volume=pa.array([volume], type=pa.uint64()),
    )
    pq.write_table(pa.table(columns), file)
    if explanation:
        with pytest.raises(Problem, match=explanation) as caught:
            load_dataset(file, METADATA, as_of_utc=CLOCK)
        assert caught.value.diagnostic["code"] == "E401_DATA"
    else:
        data = load_dataset(file, METADATA, as_of_utc=CLOCK)
        assert data.times.tolist() == [stamp // 1000]
        assert data.column("volume").tolist() == [float(volume)]


def test_import_vs_prepare():
    candles = FIXTURES / "indicators.csv"
    with pytest.raises(Problem, match="Incomplete candle") as incomplete:
        load_dataset(candles, METADATA, as_of_utc=datetime(2024, 1, 8, tzinfo=UTC))
    assert incomplete.value.diagnostic["code"] == "E401_DATA"
    data = load_dataset(candles, METADATA, as_of_utc=CLOCK)
    strategy = compile_source(expression_text("SMA(8)"))
    with pytest.raises(Problem) as bounds:
        window(strategy, data)
    assert bounds.value.diagnostic["code"] == "E_NO_EXECUTION_WINDOW"


def test_record_and_call_cache_accounting():
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    strategy = compile_source(
        strategy_text(
            lets=(
                "let first = ROC(volume,1)\nlet again = ROC(volume,1)\n"
                "let reuse = first\nlet band = MACD(1,2,2).line\nlet other = MACD(1,2,2).signal"
            )
        )
    )
    evaluator = Evaluator(strategy, data, 7)
    first, again, reuse, line, signal = [node for _, node, _ in strategy.bindings]
    assert (
        evaluator.evaluate(first)
        is evaluator.evaluate(again)
        is evaluator.evaluate(reuse)
    )
    # ROC kernel is shared, so the single zero denominator is counted once.
    # Structural readiness is counted for both call expression objects.
    assert evaluator.invalid == {"zero_denominator": 1, "warmup": 2}
    evaluator.evaluate(line)
    evaluator.evaluate(signal)
    # Field arrays contribute 1 + 2. Whole record dictionaries contribute no warmup.
    assert evaluator.invalid == {"zero_denominator": 1, "warmup": 5}
    assert len(evaluator.call_cache) == 2


def test_evaluate_unavailable_and_fill_rejection():
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    strategy = compile_source(
        strategy_text(
            lets="let value = close / (high-low)",
            sizing="equity / (close-close) * 1 price USDT",
        )
    )
    evaluator = Evaluator(strategy, data, 2)
    np.testing.assert_equal(evaluator.evaluate(strategy.bindings[0][1]), [5, 6, np.nan])
    assert evaluator.invalid["zero_denominator"] == 1
    result = execute(strategy, data)
    rows = result["events"]
    rejections = [row for row in rows if row["kind"] == "entry_rejected"]
    assert [(row["phase"], row["reason"]) for row in rejections] == [
        (3, "invalid_budget"),
        (3, "invalid_budget"),
    ]
    counts = result["summary"]["counts"]
    assert counts["entry_rejections"] == 2
    assert counts["unavailable_by_reason"]["zero_denominator"] == 3
    assert result["summary"]["final_equity"] == 1000
    assert not result["trades"]


def test_fatal_exit_preserves_failure_staging_and_destination(tmp_path):
    source = strategy_text(exit="volume == 20 volume").replace(
        "capital 1000", "capital 1e-100"
    )
    candles = tmp_path / "tiny.csv"
    header, first, second, third, *_ = (
        (FIXTURES / "indicators.csv").read_text().splitlines()
    )
    second = second.rsplit(",", 1)[0] + ",20"
    third = third.split(",", 1)[0] + ",1e-250,1e-250,1e-250,1e-250,30"
    candles.write_text("\n".join([header, first, second, third]) + "\n")
    data = load_dataset(candles, METADATA, as_of_utc=CLOCK)
    out = tmp_path / "run"
    with pytest.raises(Problem) as failed:
        publish(compile_source(source), data, out)
    assert failed.value.diagnostic["code"] == "E_NUMERIC_EXECUTION"
    assert not out.exists()
    (failure,) = tmp_path.glob(".run-*/failure.json")
    assert json.loads(failure.read_text())["diagnostic"] == failed.value.diagnostic
    assert not (failure.parent / "manifest.json").exists()


def test_evaluation_and_ledger_exclude_rows_after_execution_window(tmp_path):
    source = strategy_text(
        lets="let level = EMA(close,2)\nlet aligned = close > level",
        entry="aligned",
        exit="true and close > 16 price",
        end="2024-01-06",
        risk="risk: stop loss ATR(2)",
    )
    strategy = compile_source(source)
    original = FIXTURES / "indicators.csv"
    path = tmp_path / "changed.csv"
    rows = original.read_text().splitlines()
    rows[-2] = "2024-01-07T00:00:00Z,130,180,90,140,902"
    rows[-1] = "2024-01-08T00:00:00Z,180,240,130,220,903"
    path.write_text("\n".join(rows) + "\n")
    first, changed = (
        load_dataset(file, METADATA, as_of_utc=CLOCK) for file in (original, path)
    )
    assert first.dataset_hash != changed.dataset_hash
    first_result, changed_result = (
        execute(strategy, data) for data in (first, changed)
    )
    for result in (first_result, changed_result):
        result["equity"] = list(result["equity"])
    assert first_result == changed_result


def test_signed_zero_remains_a_finite_value():
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    strategy = compile_source(expression_text("-SMA(volume,1)"))
    evaluator = Evaluator(strategy, data, 1)
    assert evaluator.value(strategy.bindings[0][1], 1).hex() == "-0x0.0p+0"
