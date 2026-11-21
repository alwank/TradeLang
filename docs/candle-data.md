# Candle data

**V1-DATA01.** CSV and Parquet share the same normalized candle and metadata contract.

Supply one historical OHLCV dataset as CSV or Parquet. Use raw spot prices on a continuous UTC grid with one fixed candle duration. Each row describes a completed candle, timestamped at its open. Dataset metadata declares the market, units, and gap policy.

## Use your own candles

After the [first backtest](quickstart.md), check your strategy and dataset together before you run on your own prices.

- Use completed spot candles with the required OHLCV columns, ordered by opening timestamp.
- Match the strategy’s `market`, `timeframe`, and `capital` currency to the metadata’s `symbol`, `timeframe`, and `quote_currency`.
- Include the first and last complete candles in the strategy’s date range. Include earlier candles if your indicators need history before the first eligible signal.
- Check the gap policy. The default `reject` reports missing candles.

Replace the three example filenames with your own. Review any diagnostics, then confirm the resolved window and first execution open in the explanation before backtesting.

```sh
tradelang explain my-strategy.trade --data candles.csv --metadata metadata.json
```

## File formats

Both formats require exactly `timestamp,open,high,low,close,volume`. Column order is flexible.

```csv
timestamp,open,high,low,close,volume
2024-01-01T00:00:00Z,100,102,98,100,10
2024-01-02T00:00:00Z,110,115,108,112,20
2024-01-03T00:00:00Z,120,125,115,120,30
```

- **CSV** uses UTF-8, comma delimiters, and finite decimal values. Timestamps must include seconds and an explicit offset such as `Z` or `+07:00`. They may carry up to six fractional digits before grid validation. Convert epoch numbers and naive timestamps before importing.
- **Parquet** requires a timezone-aware Arrow timestamp column that can be converted exactly to UTC microseconds. Price and volume columns must be integers or floats safely convertible to binary64.

Rows must be ordered by strictly increasing, unique UTC timestamps aligned to the Unix epoch grid for the declared duration. All prices must be positive and satisfy `low <= min(open, close) <= max(open, close) <= high`. Volume is finite and nonnegative. Drop incomplete candles before export. The importer rejects malformed data and preserves the submitted order. Limits are 100 MiB and 1,000,000 rows, with an additional 512 MiB limit on decoded Parquet row groups.

## Declare metadata

Save metadata in a JSON file. This is the metadata used by the [daily fixture](fixtures/metadata.json).

```json
{
  "schema_version": 1,
  "symbol": "TESTUSDT",
  "quote_currency": "USDT",
  "timeframe": "1d",
  "calendar": "24x7",
  "timestamp_convention": "bar_open",
  "volume_unit": "base_quantity",
  "price_basis": "raw_spot",
  "gap_policy": "reject"
}
```

| Field | Accepted values |
| --- | --- |
| `schema_version` | Defaults to `1`. |
| `symbol` | Exact strategy market. Uppercase letters, digits, dots, underscores, and hyphens, up to 32 characters, starting with a letter or digit. |
| `quote_currency` | Exact strategy capital currency. Two to 12 uppercase letters or digits, starting with a letter. |
| `timeframe` | Positive integer and `m`, `h`, or `d`, up to seven days. Equal durations match, for example `24h` and `1d`. |
| `calendar`, `timestamp_convention` | `24x7` and `bar_open`, respectively. |
| `volume_unit`, `price_basis` | `base_quantity` and `raw_spot`, respectively. |
| `gap_policy` | Defaults to `reject`. Set `allow` to admit missing interior candles. |

Use `--data candles.csv --metadata metadata.json` with any CLI subcommand. The CLI also accepts [explicit metadata flags](cli.md#data-options).

## Cover the dates and supply warmup

`from 2024-01-01 to 2024-01-03` includes every complete candle in the half-open interval from January 1 at 00:00 UTC through January 4 at 00:00 UTC. Supply the first and last complete grid candles in the interval. If a multi-day grid straddles a date boundary, the partial candle is outside the execution window.

Candles before the first in-window open can initialize indicators. If history runs short, TradeLang delays the first eligible signal until structural warmup completes. It needs an eligible in-window close plus a subsequent in-window open. Use [`explain`](cli.md#explain) with the dataset to check coverage and the resolved window before backtesting.

## Choose a gap policy

The default `reject` policy requires every interval between the first and last submitted row to have exactly one candle. With `allow`, a pending order fills at the next observed open, including across a gap. Rolling windows, lookbacks, and crossings count observed rows. Protection can observe the next available open and range. The engine leaves missing prices unknown and requires window-edge coverage under either policy. Sharpe is unavailable when gaps fall inside the execution window.

## Pair candles for Volume Profile

Strategies that call `VPROFILE` use a primary OHLCV dataset and a lower-timeframe OHLCV dataset for the same market. Both inputs use the same symbol, quote currency, 24×7 calendar, raw spot prices, base-quantity volume, and UTC opening timestamps. The lower timeframe must be strictly smaller and divide the primary timeframe evenly. For example, a five-minute primary dataset can use one-minute child bars.

The engine uses primary candles for signals and fills. Each primary row uses child candles that open in its interval and close by its closing time. Every expected child timestamp within an observed primary interval must be present for that row's profile contribution to be available. An allowed primary gap contributes no interval. An allowed child gap within an observed primary interval makes the profile unavailable until the affected primary row leaves the lookback. Each input declares its own gap policy.

Provide the child file and its metadata with the [CLI data options](cli.md#data-options) or select both imported dataset IDs in the [local HTTP inspector](local-api.md#validate-or-explain-source).
