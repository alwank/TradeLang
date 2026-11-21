"""The shipped registry must agree with the fixed v1 vocabulary and metadata."""

import json
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from importlib.resources import files
from pathlib import Path

import numpy as np
import pytest
from language_cases import expression_text

from tradelang.compiler import compile_source
from tradelang.functions.contracts import Field, KernelContext, Signature
from tradelang.functions.profile import prepare_profiles
from tradelang.functions.registry import FUNCTIONS, build_registry

SOURCE = Signature(("source", "period"))
CLOSE = Signature(("period",), implicit_close=True)
PERIOD = Signature(("period",))
MACD = Signature(("period", "period", "period"), implicit_close=True)
BANDS = Signature(("source", "period", "multiplier"))

# Independent inventory of the v1 reference and schema.
EXPECTED = {
    "SMA": ((CLOSE, SOURCE), "source", (), "window"),
    "EMA": ((CLOSE, SOURCE), "source", (), "reseed"),
    "RSI": ((CLOSE,), "ratio", (), "reseed"),
    "MACD": ((MACD,), "source", ("line", "signal", "histogram"), "reseed"),
    "ATR": ((PERIOD,), "price", (), "reseed"),
    "BBANDS": ((BANDS,), "source", ("upper", "middle", "lower"), "window"),
    "HIGHEST": ((SOURCE,), "source", (), "window"),
    "LOWEST": ((SOURCE,), "source", (), "window"),
    "ROC": ((SOURCE,), "ratio", (), "interval"),
    "STDDEV": ((SOURCE,), "source", (), "window"),
    "WMA": ((CLOSE, SOURCE), "source", (), "window"),
    "RMA": ((CLOSE, SOURCE), "source", (), "reseed"),
    "VWMA": ((CLOSE, SOURCE), "source", (), "window"),
    "CMF": ((PERIOD,), "ratio", (), "window"),
    "OBV": ((Signature(()),), "volume", (), "reseed"),
    "VWAP": ((Signature(()),), "price", (), "reseed"),
    "DONCHIAN": ((PERIOD,), "price", ("upper", "middle", "lower"), "window"),
    "KELTNER": (
        (
            Signature(("period", "period", "multiplier"), implicit_close=True),
            Signature(("source", "period", "period", "multiplier")),
        ),
        "price",
        ("upper", "middle", "lower"),
        "reseed",
    ),
    "SUPERTREND": (
        (Signature(("period", "multiplier")),),
        "price",
        ("line", "direction"),
        "reseed",
    ),
    "DMI": (
        (Signature(("period", "period")),),
        "ratio",
        ("plus_di", "minus_di", "adx"),
        "reseed",
    ),
    "STOCH": (
        (Signature(("period", "period", "period")),),
        "ratio",
        ("k", "d"),
        "window",
    ),
    "STOCHRSI": (
        (Signature(("period", "period", "period", "period")),),
        "ratio",
        ("k", "d"),
        "reseed",
    ),
    "MFI": ((PERIOD,), "ratio", (), "window"),
    "CCI": ((PERIOD,), "ratio", (), "window"),
    "WILLR": ((PERIOD,), "ratio", (), "window"),
    "SAR": ((Signature(("number", "number")),), "price", (), "reseed"),
    "HMA": ((CLOSE, SOURCE), "source", (), "window"),
    "ICHIMOKU": (
        (Signature(("period", "period", "period")),),
        "price",
        ("conversion", "base", "span_a", "span_b"),
        "window",
    ),
    "AROON": ((PERIOD,), "ratio", ("up", "down", "oscillator"), "window"),
    "MOM": ((CLOSE, SOURCE), "source", (), "interval"),
    "TRANGE": ((Signature(()),), "price", (), "interval"),
    "NATR": ((PERIOD,), "ratio", (), "reseed"),
    "BBPCTB": ((BANDS,), "ratio", (), "window"),
    "BBWIDTH": ((BANDS,), "ratio", (), "window"),
    "ADL": ((Signature(()),), "volume", (), "reseed"),
    "RVOL": ((PERIOD,), "ratio", (), "interval"),
    "DEMA": ((CLOSE, SOURCE), "source", (), "reseed"),
    "TEMA": ((CLOSE, SOURCE), "source", (), "reseed"),
    "ALMA": (
        (
            Signature(("period", "number", "number"), implicit_close=True),
            Signature(("source", "period", "number", "number")),
        ),
        "source",
        (),
        "window",
    ),
    "KAMA": (
        (
            Signature(("period", "period", "period"), implicit_close=True),
            Signature(("source", "period", "period", "period")),
        ),
        "source",
        (),
        "reseed",
    ),
    "AO": ((Signature(("period", "period")),), "price", (), "window"),
    "CHOP": ((PERIOD,), "ratio", (), "window"),
    "ULTOSC": ((Signature(("period", "period", "period")),), "ratio", (), "window"),
    "TSI": (
        (
            Signature(("period", "period"), implicit_close=True),
            Signature(("source", "period", "period")),
        ),
        "ratio",
        (),
        "reseed",
    ),
    "LSMA": ((CLOSE, SOURCE), "source", (), "window"),
    "CHANDELIER": (
        (Signature(("period", "period", "multiplier")),),
        "price",
        ("long_exit", "short_exit"),
        "reseed",
    ),
    "ZIGZAG": (
        (Signature(("period", "period", "number")),),
        "price",
        ("pivot", "last_high", "last_low", "direction"),
        "reseed",
    ),
    "VPROFILE": (
        (Signature(("period", "price_literal", "number")),),
        "price",
        ("poc", "vah", "val"),
        "window",
    ),
}


def test_catalog_names_and_copies():
    package = files("tradelang")
    grammar = package.joinpath("grammar-v1.lark").read_bytes()
    schema = package.joinpath("api", "strategy.schema.json").read_bytes()
    assert grammar == Path("docs/grammar-v1.lark").read_bytes()
    assert schema == Path("docs/schemas/strategy.schema.json").read_bytes()
    terminal = re.search(rb"^FUNCTION\.2: /\\b\(\?:([A-Z|]+)\)\\b/", grammar, re.M)
    assert terminal is not None
    assert set(terminal[1].decode().split("|")) == set(FUNCTIONS)
    assert set(
        json.loads(schema)["$defs"]["Call"]["properties"]["function"]["enum"]
    ) == set(FUNCTIONS)
    assert set(json.loads(schema)["$defs"]["Field"]["properties"]["field"]["enum"]) == {
        field.name for function in FUNCTIONS.values() for field in function.fields
    }
    rows = re.findall(r"^\| ([A-Z]+) \|", Path("docs/indicators.md").read_text(), re.M)
    assert set(rows) == set(FUNCTIONS) == EXPECTED.keys()
    assert list(FUNCTIONS) == sorted(FUNCTIONS)
    assert FUNCTIONS["RSI"].scale == "points"
    assert FUNCTIONS["ROC"].scale == "fraction"
    assert FUNCTIONS["ATR"].required_columns == ("high", "low", "close")


@pytest.mark.parametrize("name", EXPECTED)
def test_descriptor_contracts(name):
    function = FUNCTIONS[name]
    assert (
        function.signatures,
        function.unit,
        tuple(f.name for f in function.fields),
        function.missing,
    ) == EXPECTED[name]


def test_immutable_and_rejects_inconsistent_catalog():
    sma = FUNCTIONS["SMA"]
    with pytest.raises(TypeError):
        FUNCTIONS["SMA"] = sma
    with pytest.raises(FrozenInstanceError):
        sma.name = "OTHER"
    with pytest.raises(ValueError, match="Duplicate"):
        build_registry((sma, sma))
    for changes, reason in [
        ({"kernel": None}, "kernel"),
        ({"unit": "invalid"}, "output unit"),
        ({"signatures": (CLOSE, PERIOD)}, "signatures"),
        ({"signatures": (Signature(("nonsense",)),)}, "roles"),
        ({"fields": (Field("x"), Field("x"))}, "fields"),
    ]:
        with pytest.raises(ValueError, match=reason):
            build_registry((replace(sma, **changes),))


@pytest.mark.parametrize(
    "order",
    [
        ("functions.registry", "compiler", "evaluator"),
        ("compiler", "evaluator", "functions.registry"),
        ("evaluator", "functions.registry", "compiler"),
    ],
)
def test_fresh_import_orders(order):
    subprocess.run(
        [sys.executable, "-c", "\n".join(f"import tradelang.{name}" for name in order)],
        timeout=15,
        check=True,
    )


@pytest.mark.parametrize("name", EXPECTED)
def test_kernel_shape_and_read_only_columns(name):
    descriptor = FUNCTIONS[name]
    signature = descriptor.signatures[0]
    series = np.array([10.0, 12.0, 14.0, 9.0, 8.0])
    series.flags.writeable = False
    args = [
        series if role == "source" else 0.2 if role == "number" else 2
        for role in signature.canonical_roles
    ]
    if name == "MACD":
        args[1] = 1
    columns = {"high": series + 1, "low": series - 1, "close": series, "volume": series}
    for value in columns.values():
        value.flags.writeable = False
    profile = None
    if descriptor.requires_profile:
        profile = prepare_profiles(
            np.arange(len(series)) * 120,
            120,
            np.arange(2 * len(series)) * 60,
            60,
            np.repeat(series, 2),
            np.ones(2 * len(series)),
            [(2, 2, 0.2)],
        )[(2, 2, 0.2)]
    context = KernelContext(
        {key: columns[key] for key in descriptor.required_columns},
        {},
        times=np.arange(len(series)) * 60_000_000
        if descriptor.requires_clock
        else None,
        profile=profile,
    )
    with np.errstate(all="ignore"):
        output = descriptor.kernel(args, context)
    if descriptor.fields:
        assert set(output) == {field.name for field in descriptor.fields}
        assert all(value.shape == series.shape for value in output.values())
    else:
        assert output.shape == series.shape


def test_internal_missing_sources_reseed_record_and_close_kernels():
    # These internal vectors exercise reset mechanics. Import rejects unavailable OHLCV.
    xs = np.array([10.0, 12.0, 14.0, 16.0, np.nan, 9.0, 9.0, 9.0, 9.0])
    context = KernelContext({}, {})
    with np.errstate(all="ignore"):
        rsi = FUNCTIONS["RSI"].kernel([xs, 2], context)
        macd = FUNCTIONS["MACD"].kernel([xs, 1, 2, 2], context)
    np.testing.assert_equal(
        rsi, [np.nan, np.nan, 100, 100, np.nan, np.nan, np.nan, 50, 50]
    )
    np.testing.assert_equal(np.isfinite(macd["line"]), [0, 1, 1, 1, 0, 0, 1, 1, 1])
    np.testing.assert_equal(np.isfinite(macd["signal"]), [0, 0, 1, 1, 0, 0, 0, 1, 1])


def test_type_and_readiness_match_public_examples():
    line = compile_source(expression_text("MACD(2,5,3).line[1]")).bindings[0][1]
    assert line.ready == 5
    assert line.args[0].args[0].ready == 6
    nested = compile_source(
        expression_text("BBANDS(EMA(volume,3),4,2).lower")
    ).bindings[0][1]
    assert nested.type.unit == (0, 1)
    assert nested.ready == 5
