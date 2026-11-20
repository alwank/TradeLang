"""Independent reconstruction of the bundle's identity inputs and integrity checks."""

import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path

import pytest
from language_cases import CLOCK, FIXTURES, METADATA, TEMPLATE

from tradelang.compiler import compile_source
from tradelang.data import canonical, load_dataset
from tradelang.engine import execute
from tradelang.report import identity, publish

TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?')
SIGNATURE = (
    "dsl_version",
    "semantics_version",
    "spec_hash",
    "dataset_hash",
    "environment_hash",
    "config_hash",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wire(obj):
    """Use the stdlib JSON encoder, then normalize its numeric tokens."""

    def number(match):
        token = match[0]
        if token.startswith('"'):
            return token
        if float(token) == 0:
            return "0"
        mantissa, _, exponent = token.partition("e")
        return mantissa.removesuffix(".0") + (f"e{int(exponent)}" if exponent else "")

    text = json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return TOKEN.sub(number, text).encode()


def result_bytes(result):
    def strip_span(obj):
        return {key: value for key, value in obj.items() if key != "span"}

    summary = {
        **result["summary"],
        "warnings": [strip_span(w) for w in result["summary"]["warnings"]],
    }
    sections = (
        ("summary", [summary]),
        ("trades", result["trades"]),
        ("equity", result["equity"]),
        ("events", result["events"]),
        ("diagnostics", map(strip_span, result["diagnostics"])),
    )
    return b"".join(
        name.encode() + b"\n" + b"".join(wire(row) + b"\n" for row in rows)
        for name, rows in sections
    )


def verify_files(run):
    manifest = json.loads((run / "manifest.json").read_bytes())
    files = {file.name for file in run.iterdir()} - {"manifest.json"}
    assert files == {entry["name"] for entry in manifest["artifact_files"]}
    for entry in manifest["artifact_files"]:
        raw = (run / entry["name"]).read_bytes()
        assert (len(raw), sha(raw)) == (entry["bytes"], entry["sha256"]), entry["name"]


@pytest.mark.parametrize("nonfinite", [float("inf"), -float("inf"), float("nan")])
def test_canonical_numbers_and_strings(nonfinite):
    obj = {"café": [1.0, -0.0, 1e-7, 1e20, '1.0 "quote"']}
    expected = '{"café":[1,0,1e-7,1e20,"1.0 \\"quote\\""]}'.encode()
    assert wire(obj) == canonical(obj).encode() == expected
    with pytest.raises(ValueError):
        canonical(nonfinite)


def test_dataset_bytes_and_policy_orthogonality():
    path = Path("docs/fixtures/core.csv")
    header = (
        b'{"calendar":"24x7","price_basis":"raw_spot","quote_currency":"USDT",'
        b'"symbol":"TESTUSDT","timeframe":86400,"timestamp_convention":"bar_open",'
        b'"volume_unit":"base_quantity"}'
    )
    candles = [
        (100, 102, 98, 100, 10),
        (110, 115, 108, 112, 20),
        (120, 125, 115, 120, 30),
    ]
    rows = b"".join(
        struct.pack("<q5d", 1704067200000000 + i * 86400000000, *candle)
        for i, candle in enumerate(candles)
    )
    expected = sha(
        b"tradelang.dataset.v1\n" + struct.pack("<I", len(header)) + header + rows
    )
    primary = load_dataset(path, METADATA, as_of_utc=CLOCK)
    alias = load_dataset(
        path, {**METADATA, "timeframe": "24h", "gap_policy": "allow"}, as_of_utc=CLOCK
    )
    assert primary.dataset_hash == alias.dataset_hash == expected
    assert primary.source_hash == alias.source_hash == sha(path.read_bytes())


def test_bundle_signature_result_stream_and_tamper(tmp_path):
    strategy = compile_source((FIXTURES / "catalog.trade").read_bytes())
    input_path = FIXTURES / "indicators.csv"
    reject = load_dataset(input_path, METADATA, as_of_utc=CLOCK)
    allow = load_dataset(
        input_path, {**METADATA, "gap_policy": "allow"}, as_of_utc=CLOCK
    )
    manifests = []
    for name, data in (("first", reject), ("repeat", reject), ("allow", allow)):
        run = tmp_path / name
        publish(strategy, data, run)
        verify_files(run)
        manifest = json.loads((run / "manifest.json").read_bytes())
        manifests.append(manifest)
        assert manifest["result_digest"] == sha(result_bytes(execute(strategy, data)))
        assert manifest["source_hash"] == sha(strategy.source)
        assert manifest["environment_hash"] == sha(
            wire(json.loads((run / "environment.json").read_bytes()))
        )
        assert manifest["run_fingerprint"] == sha(
            wire({key: manifest[key] for key in SIGNATURE})
        )
        with zipfile.ZipFile(run / "source-package.zip") as package:
            assert any(
                name.endswith("/functions/registry.py") for name in package.namelist()
            )
    first, repeat, alternate = manifests
    assert len({manifest["run_id"] for manifest in manifests}) == 3
    for key in (*SIGNATURE, "result_digest", "run_fingerprint"):
        assert first[key] == repeat[key], key
    assert first["dataset_hash"] == alternate["dataset_hash"]
    assert first["config_hash"] != alternate["config_hash"]
    assert first["run_fingerprint"] != alternate["run_fingerprint"]
    tampered = tmp_path / "first" / "source.trade"
    raw = tampered.read_bytes()
    tampered.write_bytes(b"!" + raw[1:])
    with pytest.raises(AssertionError, match="source.trade"):
        verify_files(tampered.parent)


def test_projected_spec_aliases_and_binding_names():
    a = TEMPLATE.replace("entry:", "let trend = SMA(1)\nentry:").replace(
        "when true", "when trend > 0"
    )
    b = "\ufefftradelang 1\n# alias\n" + a.replace("SMA(1)", "SMA(close,1)").replace(
        "trend >", "trend is above"
    )
    c = b.replace("trend", "another")
    original, alias, renamed = map(
        lambda text: identity(compile_source(text)), (a, b, c)
    )
    assert original["source_hash"] != alias["source_hash"]
    assert original["spec_hash"] == alias["spec_hash"]
    assert alias["spec_hash"] != renamed["spec_hash"]
