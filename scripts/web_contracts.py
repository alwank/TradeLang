"""Export the supervised API schema and language catalog for the browser."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from tradelang.api import create_app
from tradelang.compiler import GRAMMAR, GRAMMAR_V2
from tradelang.functions.profile import MAX_PROFILE_WINDOW
from tradelang.functions.registry import FUNCTIONS
from tradelang.persistence import Library

PARAMETER_NAMES = {
    "MACD": ("fast", "slow", "signal"),
    "KELTNER": ("ema_period", "atr_period", "factor"),
    "DMI": ("di_period", "adx_period"),
    "STOCH": ("period", "k_period", "d_period"),
    "STOCHRSI": ("rsi_period", "stoch_period", "k_period", "d_period"),
    "SAR": ("step", "maximum"),
    "ICHIMOKU": ("conversion", "base", "span_b"),
    "ALMA": ("period", "offset", "sigma"),
    "KAMA": ("period", "fast", "slow"),
    "AO": ("fast", "slow"),
    "ULTOSC": ("short", "medium", "long"),
    "TSI": ("slow", "fast"),
    "CHANDELIER": ("period", "atr_period", "factor"),
    "ZIGZAG": ("left", "right", "reversal"),
    "VPROFILE": ("period", "bin_width", "value_area"),
}
ROLE_TYPES = {
    "source": "price, volume, or ratio series",
    "period": "1–10,000 bars",
    "multiplier": "unsuffixed factor greater than 0 and at most 10",
    "number": "unsuffixed numeric literal",
    "price_literal": "positive price literal",
}
RELATIONSHIPS = {
    "MACD": "Fast < slow",
    "ICHIMOKU": "Conversion ≤ base ≤ span B",
    "KAMA": "Fast < slow",
    "AO": "Fast < slow",
    "SAR": "0 < step ≤ maximum ≤ 1",
    "ULTOSC": "Short < medium < long",
    "TSI": "Fast < slow",
}
SPECIAL_TYPES = {
    ("ALMA", "offset"): "unsuffixed ratio from 0 through 1",
    ("ALMA", "sigma"): "unsuffixed ratio greater than 0 and at most 100",
    ("CHOP", "period"): "2–10,000 bars",
    ("KELTNER", "source"): "price series",
    ("LSMA", "period"): "2–10,000 bars",
    ("VPROFILE", "period"): f"1–{MAX_PROFILE_WINDOW} bars",
    ("VPROFILE", "value_area"): "unsuffixed ratio greater than 0 and at most 1",
    ("ZIGZAG", "left"): "1–1,000 bars",
    ("ZIGZAG", "right"): "1–1,000 bars",
    ("ZIGZAG", "reversal"): "unsuffixed ratio greater than 0 and at most 1",
}


def signature_hint(name, signature):
    roles = signature.roles
    labels = PARAMETER_NAMES.get(name, roles)
    if name in PARAMETER_NAMES and roles[0] == "source":
        labels = ("source", *labels)
    return dict(
        arguments=[
            dict(
                name=label,
                constraint=SPECIAL_TYPES.get((name, label), ROLE_TYPES[role]),
            )
            for label, role in zip(labels, roles, strict=True)
        ],
        default="source defaults to close" if signature.implicit_close else None,
        relationship=RELATIONSHIPS.get(name),
    )


def main():
    root = Path(__file__).resolve().parents[1]
    web = root / "apps" / "web"
    with TemporaryDirectory() as directory:
        library = Library(Path(directory))
        try:
            schema = create_app(library=library).openapi()
        finally:
            library.db.dispose()
    (web / "api-schema.json").write_text(json.dumps(schema, indent=2) + "\n")

    examples = []
    for path in sorted((root / "docs" / "examples").glob("0[1-4]-*.trade")):
        source = path.read_text()
        header = re.search(r'^strategy ("[^"\n]+")', source, re.MULTILINE)
        assert header, path
        starter = re.sub(r"^(?:market|timeframe)[ \t]+[^\n]*\n", "", source, flags=re.M)
        examples.append({"name": json.loads(header[1]), "source": starter})
    catalog = {
        "keywords": sorted(
            token.lower() for token in re.findall(r"^_K_([A-Z0-9]+)\.2:", GRAMMAR, re.M)
        ),
        "version2_keywords": sorted(
            token
            for token in re.findall(
                r"^_K_[A-Z]+\.2: /\\b([a-z]+)\\b/", GRAMMAR_V2, re.M
            )
            if token not in {"available", "coalesce", "choose"}
        ),
        "choice_functions": {
            "available": "(value)",
            "coalesce": "(value, fallback)",
            "choose": "(condition, when_true, when_false)",
        },
        "functions": [
            {
                "name": name,
                "fields": [field.name for field in function.fields],
                "scale": function.scale,
                "field_scales": {
                    field.name: field.scale or function.scale
                    for field in function.fields
                    if field.scale or function.scale
                },
                "signatures": [
                    signature_hint(name, signature) for signature in function.signatures
                ],
            }
            for name, function in FUNCTIONS.items()
        ],
        "examples": examples,
    }
    (web / "src" / "lib" / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
