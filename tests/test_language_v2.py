"""Versioned composition and causal evaluation fixtures."""

import json
from pathlib import Path

import numpy as np
import pytest
from language_cases import CLOCK, FIXTURES, METADATA, strategy_text
from typer.testing import CliRunner

from tradelang.api.contracts import AST_VALIDATOR_V2
from tradelang.cli import app
from tradelang.compiler import compile_source
from tradelang.data import load_dataset, prepare_window
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem
from tradelang.report import explain, identity

V2 = "tradelang 2\n"
PARAMETERS = "param fast: count = 2 range [1 count, 5 count]\nparam slow: count = 3"


def test_named_macd_and_boolean_history_match_inline_crossing():
    path = Path(__file__).resolve().parents[1] / "docs/fixtures/macd-v2.csv"
    data = load_dataset(path, METADATA, as_of_utc=CLOCK)
    source = path.with_suffix(".trade").read_text()
    named = compile_source(
        "\ufeff# Strategy\r\ntradelang # Version\r\n2\r\n" + source.removeprefix(V2)
    )
    inline = compile_source(
        strategy_text(
            entry="MACD(2, 3, 2).line crosses above MACD(2, 3, 2).signal",
            exit="MACD(2, 3, 2).line crosses below MACD(2, 3, 2).signal",
            sizing="10% of equity",
            end="2024-01-09",
        )
    )
    spec = named.public()
    AST_VALIDATOR_V2.validate(spec)
    first = spec["bindings"][0]["expression"]["inferred_type"]
    assert first["field_readiness"] == {"line": 2, "signal": 3, "histogram": 3}
    assert named.warmup == inline.warmup == 4
    evaluator = Evaluator(named, data, 8)
    assert evaluator.value(named.entry, 3) is None
    np.testing.assert_equal(
        evaluator.evaluate(named.entry),
        Evaluator(inline, data, 8).evaluate(inline.entry),
    )
    assert len(evaluator.call_cache) == 1
    left, right = execute(named, data), execute(inline, data)
    assert list(left["equity"]) == list(right["equity"])
    fills = [event for event in left["events"] if event["kind"] == "fill"]
    assert len(fills) == 1 and fills[0]["bar_index"] == 8
    assert len(named.source) == len(named.source.decode("utf-8-sig").encode()) + 3
    assert identity(named) == identity(
        compile_source(named.source, parameters={"fast": 2.0})
    )
    assert (
        identity(named)["spec_hash"]
        != identity(compile_source(named.source, parameters={"fast": 1}))["spec_hash"]
    )


def test_reachable_records_and_profile_requirements():
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    common = "let band = KELTNER(2, 100, 2)\nlet alias = band"
    source = dict(entry="close >= alias.middle", exit="false", end="2024-01-08")
    bare = compile_source(V2 + strategy_text(lets=common, **source))
    decorated = compile_source(
        V2
        + strategy_text(
            lets=common
            + "\nlet unused = SMA(99)\nlet profile = VPROFILE(4, 1 price, 0.7).poc",
            **source,
        )
    )
    assert bare.warmup == decorated.warmup == 1
    assert [warning["code"] for warning in decorated.warnings] == ["W_UNUSED_LET"] * 2
    assert not list(decorated.calls("VPROFILE"))
    assert decorated.public()["requires_profile"] is False
    assert (
        prepare_window(bare, data).workload == prepare_window(decorated, data).workload
    )
    clean_run, decorated_run = execute(bare, data), execute(decorated, data)
    assert list(clean_run["equity"]) == list(decorated_run["equity"])
    assert (
        clean_run["summary"]["benchmark_entry_at"]
        == decorated_run["summary"]["benchmark_entry_at"]
    )
    assert "alias.middle" in explain(decorated, data)["text"]
    boundary_source = (V2 + strategy_text(lets=common, **source)).replace(
        "from 2024-01-01", "from 2024-01-04"
    )
    boundary = compile_source(boundary_source)
    assert (
        "Dataset supplied 3 observed pre-window candles."
        in explain(boundary, data)["text"]
    )
    with pytest.raises(Problem, match="no later in-window open"):
        prepare_window(
            compile_source(
                V2
                + strategy_text(
                    lets="let delayed = SMA(8)",
                    entry="close > delayed",
                    end="2024-01-08",
                )
            ),
            data,
        )
    legacy = compile_source(strategy_text(lets="let unused = SMA(3)", end="2024-01-08"))
    assert legacy.warmup == 2


def test_explicit_availability_and_conditional_preserve_causal_prefixes():
    strategy = compile_source(
        V2
        + strategy_text(
            lets="\n".join(
                (
                    "let recent = coalesce(close[2], close)",
                    "let guarded = choose(false, 1 / ((close - open) / 1 price), 0)",
                    "let selected = choose(close[1] > 12 price, close, open)",
                )
            ),
            entry="available(recent) and guarded == 0 and not available(selected)",
        )
    )
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    evaluator = Evaluator(strategy, data, 7)
    expressions = [expr for _, expr, _ in strategy.bindings] + [strategy.entry]
    assert evaluator.value(expressions[0], 0) == 10
    assert evaluator.value(expressions[0], 2) == 10
    assert evaluator.value(expressions[1], 0) == 0
    assert evaluator.value(expressions[2], 0) is None
    assert evaluator.value(strategy.entry, 0) == 1
    assert strategy.warmup == 0
    AST_VALIDATOR_V2.validate(strategy.public())
    for end in range(8):
        prefix = Evaluator(strategy, data, end)
        for expr in expressions:
            np.testing.assert_equal(
                prefix.evaluate(expr), evaluator.evaluate(expr)[: end + 1]
            )
    with pytest.raises(Problem, match="matching kinds and units"):
        compile_source(V2 + strategy_text(entry="available(coalesce(close, 1))"))


@pytest.mark.parametrize(
    "operand,value",
    [("true", True), ("false", False), ("close[1] > 0", None)],
)
def test_choice_boolean_truth_and_unknown(operand, value):
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    expressions = {
        f"available({operand})": value is not None,
        f"coalesce({operand}, true)": value if value is not None else True,
        f"coalesce({operand}, close[1] > 0)": value,
        f"choose({operand}, true, false)": value,
        f"choose({operand}, close[1] > 0, false)": None
        if value is not False
        else False,
    }
    for source, expected in expressions.items():
        strategy = compile_source(V2 + strategy_text(entry=source))
        assert Evaluator(strategy, data, 1).value(strategy.entry, 0) == expected


def test_boolean_offsets_use_observed_rows_across_allowed_gaps(tmp_path):
    path = tmp_path / "gap.csv"
    original = (FIXTURES / "indicators.csv").read_text().splitlines()
    path.write_text("\n".join([*original[:2], *original[3:]]) + "\n")
    data = load_dataset(path, {**METADATA, "gap_policy": "allow"}, as_of_utc=CLOCK)
    strategy = compile_source(
        V2
        + strategy_text(
            lets="let up = close > 11 price",
            entry="up[0] and not up[1][0]",
            end="2024-01-08",
        )
    )
    evaluator = Evaluator(strategy, data, 6)
    assert evaluator.value(strategy.entry, 0) is None
    assert evaluator.value(strategy.entry, 1) == 1
    assert evaluator.value(strategy.entry, 2) == 0
    with pytest.raises(Problem, match="Unknown field"):
        compile_source(
            V2
            + strategy_text(
                lets="let my_macd = MACD(2, 3, 2)", entry="my_macd.signl > 0"
            )
        )


@pytest.mark.parametrize(
    "expression",
    [
        "RSI(2) < 30%",
        "(RSI(2)) < 30%",
        "rsi[1] < 30%",
        "MFI(2) < 30%",
        "DMI(2, 2).adx < 30%",
    ],
)
def test_warns_about_percentage_threshold_at_the_percentage(expression):
    source = V2 + strategy_text(lets="let rsi = RSI(2)", entry=expression)
    warnings = [
        w for w in compile_source(source).warnings if w["code"] == "W_POINT_SCALE"
    ]
    (warning,) = warnings
    span = warning["span"]
    assert source.encode()[span["start_byte"] : span["end_byte"]] == b"30%"
    assert "0.3 points" in warning["message"] and "Use 30" in warning["suggestion"]
    for normalized in ("rsi / 100 < 30%", "rsi < 30"):
        assert (
            compile_source(
                V2 + strategy_text(lets="let rsi = RSI(2)", entry=normalized)
            ).warnings
            == ()
        )


@pytest.mark.parametrize(
    "args",
    [
        ["fast=2.5"],
        ["fast=0"],
        ["fast=5"],
        ["fast=true"],
        ["unknown=1"],
        ["fast=NaN"],
        ["fast=1", "fast=2"],
        ['fast="two"'],
    ],
)
def test_rejects_invalid_cli_overrides(tmp_path, args):
    path = tmp_path / "parameter.trade"
    path.write_text(
        V2 + strategy_text(lets=PARAMETERS, entry="MACD(fast, slow, 2).line > 0")
    )
    options = [part for override in args for part in ("--param", override)]
    result = CliRunner().invoke(app, ["validate", str(path), "--json", *options])
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["diagnostics"][0]["code"] in {
        "E208_PARAMETER",
        "E202_PERIOD",
    }


@pytest.mark.parametrize(
    "lets,entry",
    [
        ("let period = 2", "EMA(period) > close"),
        ("let record = MACD(2, 3, 2)", "record.line > close"),
        ("let trend = close > open", "trend[1]"),
        ("", "available(close)"),
    ],
)
def test_composition_requires_version_two(lets, entry):
    with pytest.raises(Problem):
        compile_source(strategy_text(lets=lets, entry=entry))
