"""Clause-level checks of accepted syntax, types and ordered diagnostics."""

from pathlib import Path

import pytest
from language_cases import TEMPLATE, expression_text, strategy_text

from tradelang.application import inspect_source
from tradelang.compiler import compile_source
from tradelang.model import Problem
from tradelang.report import identity

# The surface comes from the v1 grammar and the published indicator table.
INDICATORS = {
    "SMA({p})": 1,
    "SMA(close,{p})": 1,
    "EMA({p})": 1,
    "EMA(close,{p})": 1,
    "RSI({p})": 0,
    "ATR({p})": 1,
    "MACD(1,{p},2).line": 1,
    "MACD(1,{p},2).signal": 0,
    "MACD(1,{p},2).histogram": 0,
    "BBANDS(close,{p},2).upper": 1,
    "BBANDS(close,{p},2).middle": 1,
    "BBANDS(close,{p},2).lower": 1,
    "HIGHEST(close,{p})": 1,
    "LOWEST(close,{p})": 1,
    "ROC(close,{p})": 0,
    "STDDEV(close,{p})": 1,
}


@pytest.mark.parametrize("form,discount", INDICATORS.items())
@pytest.mark.parametrize("period", [1, 2, 10000])
def test_period_readiness(form, discount, period):
    if form.startswith("MACD") and period == 1:
        # The minimum slow period is 2, because fast must be strictly smaller.
        form = form.replace("1,{p},2", "1,2,{p}")
        ready = 1
    else:
        ready = period - discount
    result = compile_source(expression_text(form.format(p=period)))
    assert result.bindings[0][1].ready == result.warmup == ready


@pytest.mark.parametrize("form", INDICATORS)
@pytest.mark.parametrize(
    "period",
    ["0", "10001", "20.0", "2e1", "+20", "(20)", "10+10", "true", "close", "2 count"],
)
def test_period_errors(form, period):
    expression = form.format(p=period)
    failed = inspect_source(expression_text(expression).encode(), "validate")
    assert failed["valid"] is False and failed["spec"] is None
    (diagnostic,) = failed["diagnostics"]
    assert diagnostic["code"] == "E202_PERIOD"
    assert diagnostic["severity"] == "error"
    span = diagnostic["span"]
    raw = expression_text(expression).encode()
    assert raw[span["start_byte"] : span["end_byte"]].decode().strip(
        "()"
    ) == period.strip("()")


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("SMA()", "E203_TYPE"),
        ("EMA()", "E203_TYPE"),
        ("STDDEV(close)", "E203_TYPE"),
        ("HIGHEST(close,2,3)", "E203_TYPE"),
        ("LOWEST(2,1)", "E203_TYPE"),
        ("ROC(close > 0,1)", "E203_TYPE"),
        ("ROC(MACD(1,2,1),1)", "E203_TYPE"),
        ("SMA(close * volume,1)", "E203_TYPE"),
        ("SMA(close * close,1)", "E203_TYPE"),
        ("MACD(2,2,1).line", "E202_PERIOD"),
        ("MACD(1,2).line", "E203_TYPE"),
        ("MACD(close,1,2,1).line", "E203_TYPE"),
        ("ATR(close,2)", "E203_TYPE"),
        ("RSI(close,1)", "E203_TYPE"),
        ("SMA(1,0)", "E203_TYPE"),
        ("SMA(1,10/0)", "E206_CONSTANT_INVALID"),
        ("BBANDS(close,0,0).upper", "E202_PERIOD"),
        ("BBANDS(close,2,0).upper", "E203_TYPE"),
        ("BBANDS(close,2,11).upper", "E203_TYPE"),
        ("BBANDS(close,2,-1).upper", "E203_TYPE"),
        ("BBANDS(close,2,2%).upper", "E203_TYPE"),
        ("BBANDS(close,2,1+1).upper", "E203_TYPE"),
        ("BBANDS(close,2,true).upper", "E203_TYPE"),
        ("BBANDS(close,2,1).line", "E204_SELECTOR"),
        ("MACD(1,2,1).upper", "E204_SELECTOR"),
        ("MACD(1,2,1)[0].line", "E205_OFFSET"),
        ("MACD(1,2,1)", "E203_TYPE"),
        ("MACD(1,2,1) + 0", "E203_TYPE"),
        ("close[100001]", "E205_OFFSET"),
        ("close[-1]", "E101_SYNTAX"),
        ("ATR(2)[100000]", "E207_LIMIT"),
        ("false[1]", "E205_OFFSET"),
        ("1[0]", "E205_OFFSET"),
        ("close + volume", "E201_UNIT"),
        ("volume / 2 count", "E201_UNIT"),
        ("close ** 0.5", "E203_TYPE"),
        ("2 count ** 1", "E203_TYPE"),
        ("2 ** volume", "E203_TYPE"),
        ("1e400", "E206_CONSTANT_INVALID"),
        ("(-1)**0.5", "E206_CONSTANT_INVALID"),
        ("0**0", "E206_CONSTANT_INVALID"),
        ("10/0", "E206_CONSTANT_INVALID"),
        ("0**-1", "E206_CONSTANT_INVALID"),
        ("true + 1", "E203_TYPE"),
        ("not 1", "E203_TYPE"),
        ("close > +0", "E201_UNIT"),
        ("close > -0", "E201_UNIT"),
        ("close > 1-1", "E201_UNIT"),
        ("close > 0 volume", "E201_UNIT"),
        ("close > 0 > 2", "E101_SYNTAX"),
        ("equity > 0", "E102_UNKNOWN_NAME"),
        ("ema(1)", "E101_SYNTAX"),
        ("missing", "E102_UNKNOWN_NAME"),
        ("value", "E104_FORWARD_REFERENCE"),
        (".5", "E101_SYNTAX"),
        ("01", "E101_SYNTAX"),
        ("1.", "E101_SYNTAX"),
    ],
)
def test_compile_failure(expression, code):
    with pytest.raises(Problem) as caught:
        compile_source(expression_text(expression))
    assert caught.value.diagnostic["code"] == code


@pytest.mark.parametrize("zero", ["0", "(0)", "0.0", "0e2", "0%"])
def test_direct_ratio_zero_forms(zero):
    assert (
        compile_source(expression_text(f"close > {zero}")).bindings[0][1].type.kind
        == "boolean"
    )


@pytest.mark.parametrize(
    ("expression", "warns"),
    [
        ("RSI(1) > 30%", True),
        ("30% < RSI(1)", True),
        ("(RSI(1)) > 30%", True),
        ("RSI(1) crosses above 30%", True),
        ("RSI(1) > (30%)", False),
        ("RSI(1) > 15% + 15%", False),
        ("RSI(1)[0] > 30%", False),
        ("points > 30%", False),
        ("RSI(1) > cutoff", False),
        ("RSI(1) > 30", False),
    ],
)
def test_warning_scope(expression, warns):
    raw = strategy_text(lets="let points = RSI(1)\nlet cutoff = 30%", entry=expression)
    strategy = compile_source(raw)
    warnings = [w for w in strategy.warnings if w["code"] == "W_RSI_SCALE"]
    assert len(warnings) == int(warns)
    if warnings:
        diagnostic = warnings[0]
        span = diagnostic["span"]
        assert diagnostic["severity"] == "warning"
        assert (
            raw.encode()[span["start_byte"] : span["end_byte"]].decode() == expression
        )


@pytest.mark.parametrize(
    "prefix", ["", "tradelang 1\n", "dsl 1\r\n# Café 🐈\r\n", "\ufeff"]
)
def test_version_alias_and_source_bytes(prefix):
    data = (prefix + TEMPLATE).encode()
    result = compile_source(data)
    assert result.source == data
    assert (
        identity(result)["spec_hash"] == identity(compile_source(TEMPLATE))["spec_hash"]
    )


@pytest.mark.parametrize(
    "prefix", ["dsl 2\n", "tradelang 01\n", "dsl 1\ndsl 1\n", "dsl 1.0\n"]
)
def test_malformed_versions(prefix):
    with pytest.raises(Problem, match="Unexpected syntax"):
        compile_source(prefix + TEMPLATE)


def test_utf8_byte_span_and_nullable_diagnostic():
    raw = (
        b"\xef\xbb\xbf# "
        + "é Ｔ🐈".encode()
        + b"\r\n"
        + strategy_text(entry="\tunknown").encode()
    )
    bad = inspect_source(raw, "validate")
    (diagnostic,) = bad["diagnostics"]
    start = raw.index(b"unknown")
    assert diagnostic == {
        "code": "E102_UNKNOWN_NAME",
        "message": "Unknown or unavailable name unknown",
        "severity": "error",
        "span": {
            "start_byte": start,
            "end_byte": start + 7,
            "start_line": 7,
            "end_line": 7,
            "start_column": 9,
            "end_column": 16,
        },
        "suggestion": None,
        "data_row": None,
        "node_id": None,
        "details": {},
    }
    invalid = inspect_source(b"\xff", "validate")
    assert invalid["valid"] is False
    assert invalid["diagnostics"][0]["span"] is None
    assert invalid["diagnostics"][0]["code"] == "E101_SYNTAX"


def test_function_diagnostics_use_trade_language_and_exact_spans():
    raw = (
        b"\xef\xbb\xbf# "
        + "é🐈".encode()
        + b"\r\n"
        + strategy_text(entry="ema(2) > close").replace("\n", "\r\n").encode()
    )
    (diagnostic,) = inspect_source(raw, "validate")["diagnostics"]
    assert diagnostic["code"] == "E101_SYNTAX"
    assert diagnostic["suggestion"] == "Use EMA(...)"
    span = diagnostic["span"]
    assert raw[span["start_byte"] : span["end_byte"]] == b"ema"
    assert span["start_line"] == span["end_line"]
    assert span["end_column"] - span["start_column"] == 3

    (diagnostic,) = inspect_source(
        strategy_text(entry="EMA(1, 2, 3) > close").encode(), "validate"
    )["diagnostics"]
    assert diagnostic["code"] == "E203_TYPE"
    assert "EMA(period) or EMA(source, period)" in diagnostic["message"]

    (diagnostic,) = inspect_source(
        strategy_text(entry="MACD(1, 2, 1).signa > close").encode(), "validate"
    )["diagnostics"]
    assert diagnostic["code"] == "E204_SELECTOR"
    assert diagnostic["suggestion"] == "Use .signal"

    (diagnostic,) = inspect_source(b'strategy "Example" entry:', "validate")[
        "diagnostics"
    ]
    assert diagnostic["suggestion"] == "Expected 'when'"


@pytest.mark.parametrize(
    "path",
    sorted(Path("docs/examples").glob("*.trade")),
    ids=lambda path: path.name,
)
def test_published_examples_compile(path):
    assert compile_source(path.read_bytes()).public()["dsl_version"] == 1


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"lets": "let alpha = 1\nlet alpha = true"}, "E103_DUPLICATE_BINDING"),
        ({"lets": "let alpha = beta\nlet beta = 1"}, "E104_FORWARD_REFERENCE"),
        ({"lets": "let open = 1"}, "E103_DUPLICATE_BINDING"),
        ({"sizing": "SMA(equity,0) USDT"}, "E203_TYPE"),
        ({"sizing": "110% of equity"}, "E302_SIZING"),
        ({"risk": "risk: stop loss -1 price"}, "E303_RISK"),
        ({"end": "2023-12-31"}, "E402_WINDOW"),
    ],
)
def test_context_errors(changes, code):
    with pytest.raises(Problem) as caught:
        compile_source(strategy_text(**changes))
    assert caught.value.diagnostic["code"] == code
