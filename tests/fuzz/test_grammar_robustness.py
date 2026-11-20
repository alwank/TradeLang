"""Bounded lexical mutations and exact compiler resource boundaries."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st
from language_cases import TEMPLATE, expression_text, strategy_text

from tradelang.compiler import compile_source
from tradelang.model import Problem

SOURCE = TEMPLATE.encode()
COMPILE_CODES = {
    "E101_SYNTAX",
    "E102_UNKNOWN_NAME",
    "E103_DUPLICATE_BINDING",
    "E104_FORWARD_REFERENCE",
    "E201_UNIT",
    "E202_PERIOD",
    "E203_TYPE",
    "E204_SELECTOR",
    "E205_OFFSET",
    "E206_CONSTANT_INVALID",
    "E207_LIMIT",
    "E302_SIZING",
    "E303_RISK",
    "E402_WINDOW",
}


@given(
    at=st.integers(0, len(SOURCE)),
    erase=st.integers(0, 24),
    insert=st.binary(max_size=32),
)
def test_bounded_source_splices(at, erase, insert):
    source = SOURCE[:at] + insert + SOURCE[at + erase :]
    try:
        result = compile_source(source)
    except Problem as trouble:
        diagnostic = trouble.diagnostic
        assert diagnostic["code"] in COMPILE_CODES
        assert diagnostic["severity"] == "error"
        if (span := diagnostic["span"]) is not None:
            assert 0 <= span["start_byte"] <= span["end_byte"] <= len(source)
    else:
        assert result.source == source
        public = result.public()
        assert public["dsl_version"] == 1
        assert public["entry"]["condition"]["inferred_type"]["kind"] == "boolean"


@given(
    title=st.text(alphabet='ab ##Ωé🎵\t\u00a0\\"', min_size=1, max_size=16).filter(
        str.isprintable
    ),
    newline=st.sampled_from(["\n", "\r\n"]),
    bom=st.booleans(),
)
def test_json_strings_comments_and_unicode_spans(title, newline, bom):
    header = json.dumps(title, ensure_ascii=bom)
    source = TEMPLATE.replace('"Golden next-open ledger"', header).replace(
        "\n", newline
    )
    source = (
        ("\ufeff" if bom else "") + "dsl 1 # hash here. Ω # comment" + newline + source
    ).encode()
    assert compile_source(source).name == title


@pytest.mark.parametrize(
    "fragment",
    [
        "1. ",
        ".5",
        "01",
        "1e+",
        "1e -2",
        "truefalse",
        "SMAA(1)",
        "close[01]",
        "close[-0]",
        "1;;",
        "1,2",
    ],
)
def test_invalid_number_keyword_and_postfix_boundaries(fragment):
    with pytest.raises(Problem) as problem:
        compile_source(expression_text(fragment))
    assert problem.value.diagnostic["code"] in COMPILE_CODES


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("sell all", "sell"),
        lambda s: s.replace("exit:", "entry:"),
        lambda s: s.replace("market TESTUSDT", "market TESTUSDT\ndsl 1"),
        lambda s: s.replace('"Golden next-open ledger"', r'"bad\q"'),
        lambda s: s.replace("calendar 24x7", "calendar"),
        lambda s: s.replace(
            "fee 0 bps per side", "fee 0 bps per side fee 0 bps per side"
        ),
    ],
)
def test_invalid_section_and_string_boundaries(mutate):
    with pytest.raises(Problem) as problem:
        compile_source(mutate(TEMPLATE))
    assert problem.value.diagnostic["code"] == "E101_SYNTAX"


def bounded(source, reason):
    with pytest.raises(Problem, match=reason) as problem:
        compile_source(source)
    assert problem.value.diagnostic["code"] == "E207_LIMIT"


def test_source_byte_limit():
    source = TEMPLATE.encode() + b"#"
    source += b"x" * (65536 - len(source))
    assert compile_source(source).source == source
    bounded(source + b"x", "64 KiB")


def test_expression_depth_and_postfix_limits():
    grouped = "(" * 64 + "1" + ")" * 64
    compile_source(expression_text(grouped))
    bounded(expression_text(f"({grouped})"), "depth")
    compile_source(expression_text("close" + "[0]" * 63))
    bounded(expression_text("close" + "[0]" * 64), "Postfix chain")


def balanced_sum(leaves):
    if leaves == 1:
        return "1"
    left = leaves // 2
    return f"({balanced_sum(left)}+{balanced_sum(leaves - left)})"


def test_expression_node_limit():
    # 681 number nodes, 680 additions and 680 groups, plus five strategy roots/children.
    at_limit = f"(({balanced_sum(681)}))"
    compile_source(expression_text(at_limit))
    bounded(expression_text(f"({at_limit})"), "node limit")


def test_bindings_and_call_limit():
    bindings = "\n".join(f"let v{i} = ATR({i + 1})" for i in range(128))
    compile_source(strategy_text(lets=bindings, entry="ATR(1) > 0"))
    bounded(strategy_text(lets=bindings, entry="ATR(129) > 0"), "indicator calls")
    bounded(strategy_text(lets=bindings + "\nlet extra = 1"), "128 lets")


def test_history_and_timeframe_ceiling():
    assert compile_source(expression_text("close[100000]")).warmup == 100000
    bounded(expression_text("close[100000][1]"), "History exceeds")
    assert compile_source(TEMPLATE.replace("1d", "7d")).seconds == 604800
    bounded(TEMPLATE.replace("1d", "8d"), "timeframe")
