import json
import math
from dataclasses import replace

import numpy as np
import pytest
from test_contracts import cli, parquet
from test_golden import FIX, META, scenario

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.evaluator import Evaluator


def average(values):
    return math.fsum(values) / len(values)


def rolling(values, period, statistic):
    out = [math.nan] * len(values)
    for end in range(period, len(values) + 1):
        window = values[end - period : end]
        if all(map(math.isfinite, window)):
            out[end - 1] = statistic(window)
    return out


def smooth(values, period, weight):
    out = []
    active = []
    for value in values:
        if not math.isfinite(value):
            active.clear()
            out.append(math.nan)
            continue
        if len(active) < period:
            active.append(value)
            out.append(average(active) if len(active) == period else math.nan)
        else:
            out.append(out[-1] + weight * (value - out[-1]))
    return out


def expected_indicators(values):
    _, highs, lows, closes, volumes = values.T.tolist()
    stddev = rolling(
        closes, 3, lambda xs: math.sqrt(average([(x - average(xs)) ** 2 for x in xs]))
    )
    sma = rolling(closes, 3, average)
    ema = smooth(closes, 3, 0.5)
    momentum = [math.nan] + [cur - prev for prev, cur in zip(closes, closes[1:])]
    gain = smooth([max(x, 0) for x in momentum], 2, 0.5)
    loss = smooth([max(-x, 0) for x in momentum], 2, 0.5)
    rsi = [100 * g / (g + loss_) if g + loss_ else 50 for g, loss_ in zip(gain, loss)]
    macd = [a - b for a, b in zip(smooth(closes, 2, 2 / 3), ema)]
    signal = smooth(macd, 2, 2 / 3)
    ranges = [highs[0] - lows[0]] + [
        max(high, prev) - min(low, prev)
        for prev, high, low in zip(closes, highs[1:], lows[1:])
    ]
    return {
        "SMA(volume,3)": rolling(volumes, 3, average),
        "EMA(3)": ema,
        "RSI(2)": rsi,
        "ATR(2)": smooth(ranges, 2, 0.5),
        "MACD(2,3,2).line": macd,
        "MACD(2,3,2).signal": signal,
        "MACD(2,3,2).histogram": [a - b for a, b in zip(macd, signal)],
        "BBANDS(close,3,2).middle": sma,
        "BBANDS(close,3,2).upper": [a + 2 * b for a, b in zip(sma, stddev)],
        "BBANDS(close,3,2).lower": [a - 2 * b for a, b in zip(sma, stddev)],
        "HIGHEST(high,3)[1]": [math.nan] + rolling(highs, 3, max)[:-1],
        "LOWEST(low,3)": rolling(lows, 3, min),
        "ROC(close,2)": [math.nan] * 2
        + [x / base - 1 for base, x in zip(closes, closes[2:])],
        "STDDEV(close,3)": stddev,
    }


def test_indicator_scalar_parity_and_future_perturbation():
    base = load_dataset(FIX / "indicators.csv", META)
    values = np.concatenate(
        [base.values, base.values * 1.1, base.values * 0.7, base.values * 2.1]
    )
    data = replace(base, values=values)
    source = (FIX / "core.trade").read_text()
    for expr, expected in expected_indicators(values).items():
        s = compile_source(source.replace("entry:", f"let v = {expr}\nentry:"))
        node = s.bindings[0][1]
        whole = Evaluator(s, data, len(values) - 1).evaluate(node)
        np.testing.assert_allclose(whole, expected, rtol=1e-12, atol=1e-12)
        for end in range(len(values)):
            prefix = Evaluator(s, data, end).evaluate(node)
            np.testing.assert_equal(whole[: end + 1], prefix)
            changed = values.copy()
            changed[end + 1 :] *= 1.7
            extended = np.concatenate([changed, base.values])
            result = Evaluator(
                s, replace(data, values=extended), len(extended) - 1
            ).evaluate(node)
            np.testing.assert_equal(result[: end + 1], prefix)


def test_ema_reseeds_after_invalid_source(tmp_path):
    s, d = scenario(
        "frozen-atr",
        lets="let v = EMA(close / (high - low),2)",
        rows={1: "100,100,100,100,20"},
        tmp_path=tmp_path,
    )
    # The invalid second row discards the first seed. Rows 2 and 3 seed the new one.
    out = Evaluator(s, d, 3).evaluate(s.bindings[0][1])
    np.testing.assert_allclose(out, [np.nan, np.nan, np.nan, (110 / 20 + 120 / 21) / 2])


def test_final_candle_cannot_change_queued_orders(tmp_path):
    source, data = scenario(exit="close >= 112 price")
    _, altered = scenario(rows={2: "80,85,75,80,30"}, tmp_path=tmp_path)
    full, changed = (execute(source, candles) for candles in (data, altered))
    prior_full = [e for e in full["events"] if e["bar_index"] < 2]
    assert prior_full == [e for e in changed["events"] if e["bar_index"] < 2]
    assert [e["reason"] for e in prior_full if e["kind"] == "order_queued"] == [
        "buy",
        "sell",
    ]
    assert full["summary"]["final_equity"] != changed["summary"]["final_equity"]


@pytest.mark.parametrize("fixture", sorted(FIX.glob("*.csv")), ids=lambda p: p.stem)
def test_golden_input_formats_match_installed_cli(tmp_path, fixture):
    src, _ = scenario(fixture.stem, exit="close >= 112 price")
    strategy = tmp_path / "strategy.trade"
    strategy.write_bytes(src.source)
    converted = tmp_path / "data.parquet"
    parquet(fixture, converted)
    compared = []
    for idx, data in enumerate((fixture, converted)):
        out = tmp_path / str(idx)
        code, response = cli(
            "backtest",
            strategy,
            "--data",
            data,
            "--metadata",
            FIX / "metadata.json",
            "--out",
            out,
        )
        assert code == 0, response
        result = response["result"]
        manifest = (out / "manifest.json").read_text()
        compared.append(
            (
                json.loads(manifest)["dataset_hash"],
                result["run_fingerprint"],
                result["result_digest"],
                result["summary"],
                (out / "events.jsonl").read_bytes(),
                (out / "equity.csv").read_bytes(),
            )
        )
    assert compared[0] == compared[1]
