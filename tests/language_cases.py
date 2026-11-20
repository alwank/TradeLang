"""Stable inputs for the language-hardening suites."""

import json
from datetime import UTC, datetime
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "language-hardening"
BASELINE = "f7f9b47f310ce825e900f3753c59e62a53625927"
CLOCK = datetime(2024, 2, 1, tzinfo=UTC)
METADATA = json.loads((FIXTURES / "metadata.json").read_text())
TEMPLATE = (FIXTURES / "template.trade").read_text()


def strategy_text(
    *,
    lets="",
    entry="true",
    exit="close >= 112 price",
    sizing="100% of equity",
    risk="",
    end="2024-01-03",
):
    return (
        TEMPLATE.replace("entry:", f"{lets}\nentry:")
        .replace("when true", f"when {entry}")
        .replace("close >= 112 price", exit)
        .replace("100% of equity", sizing)
        .replace("backtest:", f"{risk}\nbacktest:")
        .replace("2024-01-03", end)
    )


def expression_text(expression):
    return strategy_text(lets=f"let value = {expression}")
